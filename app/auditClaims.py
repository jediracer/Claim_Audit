# import dependencies
import pandas as pd
import mysql.connector as mc
import pdfkit as pdf
import numpy as np
# import os
# import json
# from flask import jsonify

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

    if numOrPer == 'num':
        factor = numPer
    else:
        factor = float(numPer)/100

    # check divison selection
    if div == 'NAC':
        return 204
    else:

        # get all paid claims in date range
        claims_sql = '''
                        SELECT c.claim_id, c.claim_nbr, c.paid_amount, c.paid_date, s.update_by, MAX(s.status_id)
                        FROM claims c
                        INNER JOIN claim_status s
                            USING(claim_id)
                        WHERE c.paid_amount > 0
                            AND s.status_desc_id = 8
                            AND c.paid_date BETWEEN '{BegDate}' AND '{EndDate}'
                            AND s.update_by <> 'JARED BEHLER'
                        GROUP BY c.claim_id;           
                    '''.format(BegDate=begDate, EndDate=endDate)

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

    # # get claims within each processors limit
    # for index, row in adj_limits_df.iterrows():
    #     # filter claims_df by adj_limits_df
    #     filtered_df = claims_df[(claims_df['adjuster'] == row['adjuster']) &
    #                             (claims_df['paid_amount'] <= row['authority'])]

    #     if numOrPer == 'num':
    #         factor = numPer
    #     else:
    #         perOfClaims = float(numPer)/100
    #         factor = filtered_df.shape[0] * perOfClaims

    #     # Random sample of results
    #     # If less than 5 then select all
    #     if filtered_df.shape[0] < 5:
    #         random_df = filtered_df
    #     else:
    #         if numOrPer == 'num':
    #             factor = numPer
    #         else:
    #             factor = max(5,filtered_df.shape[0] * float(numPer)/100)
    #         random_df = filtered_df.sample(n=factor, random_state=13)

    #     # Add column to filtered_df with adjuster limit
    #     random_df['authority'] = row['authority']
    #     # Remove column 'MAX(s.status_id)' 
    #     random_df.drop(columns=['MAX(s.status_id)'], inplace=True)
    #     # add random sample to audit_df
    #     audit_df = pd.concat([audit_df, random_df])

    # get list of adjusters
    adjusters = np.unique(adj_limits_df['adjuster'].tolist())

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

    # # convert columns list to string
    # db_columns = ['claim_id', 'division', 'claim_nbr', 'paid_amount', 'paid_date', 'adjuster', 'authority']
    # db_cols = ", ".join(db_columns)
    
    # # insert into sql
    # for index, rows in audit_df.iterrows():
    #     audit_sql = '''INSERT INTO claims ({columns}) VALUES ({claimId}, "Frost", "{claimNbr}", {paidAmt}, "{paidDate}", "{adj}", {auth});'''.format(columns=db_cols,
    #                     claimId=rows['claim_id'], claimNbr=rows['claim_nbr'], paidAmt=rows['paid_amount'], paidDate=rows['paid_date'], adj=rows['adjuster'],
    #                     auth=rows['authority'])

    #     # Add to claim_audit database
    #     mysql_q(mysql_u, mysql_pw, mysql_host, 'claim_audit', audit_sql, 0, 1)
    return audit_df


def claimsAuditReport():
    # create claims to audit report
    audit_list_sql = '''SELECT claim_nbr AS 'Claim Number',
                        paid_amount AS Amount,
                        paid_date, 
                        adjuster, 
                        authority, 
                        audit_amount, 
                        audit_date
                        FROM claims
                        WHERE audit_date IS NULL;'''
    audit_list = mysql_q(mysql_u, mysql_pw, mysql_host, 'claim_audit', audit_list_sql, 1, 0)
    audit_list_df = pd.DataFrame(audit_list[0])
    audit_list_df.columns = audit_list[1]
    audit_list_df['audit_amount'] = audit_list_df['audit_amount'].astype(str).replace({'None':''})
    audit_list_df['audit_date'] = audit_list_df['audit_date'].astype(str).replace({'None':''})
    audit_list_html = '../../temp/audit_list.html'
    audit_list_df.to_html(audit_list_html)
    audit_list_pdf = '../../reports/audit_list.pdf'
    pdf.from_file(audit_list_html, audit_list_pdf) 
    return 200

df = get_Audit_Claims('2022-06-06', '2022-06-10', 'frost', 'num', 5)
print(df)