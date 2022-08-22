# Conda claimaudit

# Import Depnedencies
from flask import Flask, render_template, request, jsonify, redirect, url_for
from flask_mysqldb import MySQL, MySQLdb
import pandas as pd
import os
import mysql.connector as mc
import numpy as np
import datetime;

from config import vgc_host, vgc_u, vgc_pw, mysql_host, mysql_u, mysql_pw

# MySQL
def mysql_q (u, p, h, db, sql, cols, commit):
    # cols (0 = no, 1 = yes)
    # commit (select = 0, insert/update = 1)

    # connect to db
    if db == 'MULTI':
        cnx = mc.connect(user=u, password=p, host=h) 
    else:      
        cnx = mc.connect(user=u, password=p, host=h, database=db)
        
    cursor = cnx.cursor()

    # commit?
    if commit == 1:
        cursor.execute(sql)
        cnx.commit()
        sql_result = 0     
    else:
        cursor.execute(sql)
        sql_result = cursor.fetchall()

    # columns ?
    if cols == 1:
        columns=list([x[0] for x in cursor.description])
        # close connection
        cursor.close()
        cnx.close()
        # return query result [0] and columns [1]
        return sql_result, columns
    else:
        # close connection
        cursor.close()
        cnx.close()
        # return query result
        return sql_result

# getAuditClaims
def get_Audit_Claims(begDate, endDate, div, numOrPer, numPer):

    adj_limits_sql = '''
                        SELECT adjuster, authority, effective_date
                        FROM authority;'''

    adj_limits = mysql_q(mysql_u, mysql_pw, mysql_host, 'claim_audit', adj_limits_sql, 1, 0)
    # create df from query results
    adj_limits_df = pd.DataFrame(adj_limits[0])
    # get column names from results
    adj_limits_df.columns = adj_limits[1]

    # get list of adjusters
    adjusters = np.unique(adj_limits_df['adjuster'].tolist())

    if numOrPer == 'num':
        factor = numPer
    else:
        factor = float(numPer)/100

    # check divison selection
    if div == 'NAC':
        return 204
    else:

        adj_list = ', '.join(f"'{adj}'" for adj in adjusters)  
        # get all paid claims in date range
        claims_sql = '''
                        SELECT c.claim_id, c.claim_nbr, c.paid_amount, c.paid_date, s.update_by, MAX(s.status_id)
                        FROM claims c
                        INNER JOIN claim_status s
                            USING(claim_id)
                        WHERE c.paid_amount > 0
                            AND s.status_desc_id = 8
                            AND c.paid_date BETWEEN '{BegDate}' AND '{EndDate}'
                            AND s.update_by IN ({adjusters})
                        GROUP BY c.claim_id;           
                    '''.format(BegDate=begDate, EndDate=endDate, adjusters = adj_list)

        # run sql query
        claims = mysql_q(vgc_u, vgc_pw, vgc_host, 'visualgap_claims', claims_sql, 1, 0)
        # create df from query results
        claims_df = pd.DataFrame(claims[0])
        # get column names from results
        claims_df.columns = claims[1]
        claims_df.rename(columns = {'update_by':'adjuster'}, inplace = True)

    # create audit_df for results
    audit_columns = ['claim_id', 'claim_nbr', 'paid_amount', 'paid_date', 'adjuster', 'authority']
    audit_df = pd.DataFrame(columns = audit_columns)

    # add adjuster authorization limit to each claim
    auth_limits=[]

    for index, row in claims_df.iterrows():
        lim_sql = '''
                SELECT authority
                FROM authority
                WHERE adjuster = '{adjuster}'
                AND effective_date <= '{paid_date}'
                ORDER BY effective_date DESC
                LIMIT 1;
                '''.format(adjuster = row['adjuster'], paid_date = row['paid_date'])
        adj_limit = mysql_q(mysql_u, mysql_pw, mysql_host, 'claim_audit', lim_sql, 1, 0)
        auth_limits.append(adj_limit[0][0][0])

    claims_df.insert(6, "authority", auth_limits)

    # select random claims within the adjuster's limit for audit
    for adjuster in adjusters:
        # filter claims_df by adj_limits_df
        filtered_df = claims_df[(claims_df['adjuster'] == adjuster) &
                                (claims_df['paid_amount'] <= claims_df['authority'])]

        if numOrPer == 'num':
            factor = numPer
        else:
            perOfClaims = float(numPer)/100
            factor = filtered_df.shape[0] * perOfClaims

        # Random sample of results
        # If less than 5 then select all
        if filtered_df.shape[0] < 5:
            random_df = filtered_df
        else:
            if numOrPer == 'num':
                factor = numPer
            else:
                factor = max(5,filtered_df.shape[0] * float(numPer)/100)
            random_df = filtered_df.sample(n=factor, random_state=13)

        # Remove column 'MAX(s.status_id)'
        random_df.drop(columns=['MAX(s.status_id)'], inplace=True)
        # add random sample to audit_df
        audit_df = pd.concat([audit_df, random_df])   

    # convert columns list to string
    db_columns = ['claim_id', 'division', 'claim_nbr', 'paid_amount', 'paid_date', 'adjuster', 'authority', 'batch_id']
    db_cols = ", ".join(db_columns)

    # create batch ID
    batchId = str(datetime.datetime.now().timestamp())
    
    # insert into sql
    for index, rows in audit_df.iterrows():
        audit_sql = '''INSERT INTO claims ({columns}) VALUES ({claimId}, "Frost", "{claimNbr}", {paidAmt}, "{paidDate}", "{adj}", {auth}, {batch});'''.format(columns=db_cols,
                        claimId=rows['claim_id'], claimNbr=rows['claim_nbr'], paidAmt=rows['paid_amount'], paidDate=rows['paid_date'], adj=rows['adjuster'],
                        auth=rows['authority'], batch=batchId)

        # Add to claim_audit database
        mysql_q(mysql_u, mysql_pw, mysql_host, 'claim_audit', audit_sql, 0, 1)
    
    # add dates to dates_audited table
    # convert strings to datetimes
    last_audit_date = datetime.datetime.strptime(endDate, '%Y-%m-%d')

    audit_date_sql = '''UPDATE dates_audited SET date_audited = "{audit_date}" WHERE division = "{division}";'''.format(audit_date=last_audit_date, division=div)
    # run UPDATE query
    mysql_q(mysql_u, mysql_pw, mysql_host, 'claim_audit', audit_date_sql, 0, 1)
        
    return 201

def getLastAuditDates():

    # get last date audited
    frost_date_sql = '''SELECT date_audited
                  FROM dates_audited
                  WHERE division = "frost";'''
    
    frost_date_result = mysql_q(mysql_u, mysql_pw, mysql_host, 'claim_audit', frost_date_sql, 1, 0)

    frost_date_value = []
    frost_end_date_value = []
    for date in frost_date_result[0][0]:
        frost_date_value.append(str(date + datetime.timedelta(days=1)))
        frost_end_date_value.append(str(date + datetime.timedelta(days=7)))

    nac_date_sql = '''SELECT date_audited
                  FROM dates_audited
                  WHERE division = "nac";'''

    nac_date_result = mysql_q(mysql_u, mysql_pw, mysql_host, 'claim_audit', nac_date_sql, 1, 0)

    nac_date_value = []
    nac_end_date_value = []
    for date in nac_date_result[0][0]:
        nac_date_value.append(str(date + datetime.timedelta(days=1)))
        nac_end_date_value.append(str(date + datetime.timedelta(days=7)))

    return frost_date_value, frost_end_date_value, nac_date_value, nac_end_date_value

app = Flask(__name__)

app.config['MYSQL_HOST'] = mysql_host
app.config['MYSQL_USER'] = mysql_u
app.config['MYSQL_PASSWORD'] = mysql_pw
app.config['MYSQL_DB'] = 'claim_audit'
app.config['MYSQL_CURSORCLASS'] = 'DictCursor'
mysql = MySQL(app)

@app.route('/')
def index():
    error_msg = ''
    msg = ''

    frost_date_value, frost_end_date_value, nac_date_value, nac_end_date_value = getLastAuditDates()

    return render_template('index.html', comp_msg = msg, err_msg = error_msg, frost_date=frost_date_value, nac_date=nac_date_value,
                            nac_end_date=nac_end_date_value, frost_end_date=frost_end_date_value)

@app.route('/auditClaims')
def auditClaims():#CONCAT('$', FORMAT(paid_amount,2))
    audit_list_sql = '''SELECT claim_id, claim_nbr, FORMAT(paid_amount,2) AS paid_amount, DATE_FORMAT(paid_date, '%Y-%m-%d') AS paid_date, 
                            adjuster, CONCAT('$', FORMAT(authority,2)) AS authority, 
                            IFNULL(CONCAT('$', FORMAT(audit_amount,2)),'') AS audit_amount, IFNULL(notes,'') AS notes
                        FROM claims
                        WHERE audit_date IS NULL
                            OR (NOT paid_amount = audit_amount
                                AND notes = '');'''

    audit_list_count_sql = '''SELECT COUNT(claim_nbr)
                              FROM claims
                              WHERE audit_date IS NULL
                                OR (NOT paid_amount = audit_amount
                                    AND notes = '');'''
    # collect records
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cur.execute(audit_list_sql)
    data = cur.fetchall()
    # get number of records
    cur2 = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cur2.execute(audit_list_count_sql)
    rec_count = cur2.fetchall()[0]['COUNT(claim_nbr)']
 
    return render_template('auditClaims.html', records = data, rec_count = rec_count)

@app.route('/reports')
def reports():
    summary_sql = '''SELECT FORMAT(SUM(IF(paid_amount = audit_amount,0,1)),0) AS error,
                            FORMAT(SUM(IF(paid_amount = audit_amount,1,0)),0) AS correct 
                        FROM claims
                        WHERE NOT ISNULL(audit_date);
                    '''

    # collect records
    summary_data = mysql_q(mysql_u, mysql_pw, mysql_host, 'claim_audit', summary_sql, 1, 0)

    # get values and label
    values = []
    for num in summary_data[0][0]:
        values.append(int(num))
    labels = summary_data[1]

    return render_template('reports.html', labels = labels, values=values)

@app.route('/', methods=['POST'])
def getAuditClaims():
    error_msg = ''
    msg = ''
    err = 0
    numPer = 0
    user_input = {'div_sel':request.form.get('div_sel'), 'begin_date':request.form.get('begin_date'), 'end_date':request.form.get('end_date'),
                    'claim_sel':request.form.get('claim_sel'), 'nbr_claims':request.form.get('nbr_claims'), 
                    'percent_claims':request.form.get('percent_claims')}

    # error checking
    if user_input["begin_date"] == '':
        error_msg = error_msg + " Missing 'Start Date'. "
        err += 1
    if user_input["end_date"] == '':
        error_msg = error_msg + " Missing 'End Date'. "
        err += 1
    if user_input["begin_date"] > user_input["end_date"]:
        error_msg = error_msg + " 'Start Date' cannot be after 'End Date'. "
        err += 1
    if user_input["claim_sel"] == 'num':
        numPer = 1
        if user_input["nbr_claims"] == '':
            claims_factor = 5
        else:
            claims_factor = user_input["nbr_claims"]
    else:
        if user_input["percent_claims"] == '':
            claims_factor = "10"
        else:
            claims_factor = user_input["percent_claims"]

    if numPer == 1:
        clms_fact_msg = claims_factor
    else:
        clms_fact_msg = claims_factor + "% of "   

    if err > 0:
        frost_date_value, frost_end_date_value, nac_date_value, nac_end_date_value = getLastAuditDates()
        return render_template('index.html', comp_msg = msg, err_msg = error_msg, frost_date=frost_date_value, nac_date=nac_date_value,
                            nac_end_date=nac_end_date_value, frost_end_date=frost_end_date_value)

    # run getAuditClaims
    result = get_Audit_Claims(user_input["begin_date"], user_input["end_date"], user_input["div_sel"], user_input["claim_sel"], claims_factor)

    # create successful message 
    if result == 204:
        msg = 'Currently only Frost claims can be pulled.'
    else:
        msg = 'Up to {clms_fact} claims processed by each adjuster between {begin_date} and {end_date} by {div_sel} have been selected and are ready for review.'.format(clms_fact=clms_fact_msg,
            begin_date=user_input["begin_date"], end_date=user_input["end_date"], div_sel=user_input["div_sel"])

    frost_date_value, frost_end_date_value, nac_date_value, nac_end_date_value = getLastAuditDates()

    return render_template('index.html', comp_msg = msg, err_msg = error_msg, frost_date=frost_date_value, nac_date=nac_date_value,
                            nac_end_date=nac_end_date_value, frost_end_date=frost_end_date_value)

@app.route("/ajax",methods=["POST","GET"])
def ajax():
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)    
    if request.method == 'POST':
        getid = request.form['claim_nbr']
        getamt = request.form['audit_amt']
        getnotes = request.form['audit_notes']
        user = os.getlogin()
        cur.execute("UPDATE claims SET audit_amount = %s, audit_by = %s, audit_date = CURDATE(), notes = %s WHERE claim_nbr = %s ", [getamt, user, getnotes, getid])
        mysql.connection.commit()       
        cur.close()
    return jsonify('Record updated successfully')

if __name__ == '__main__':
    app.run(debug=True)