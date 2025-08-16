import mysql.connector as mysql
mycon = mysql.connect(host='local host',
                      user='root',
                      passwd='2001')

def makeunib():
    cursor=mycon.cursor()
    cursor.execute('create database if not exists UNIB')
    cursor.execute("use UNIB")
    cursor.execute("create table if not exists USER(ID varchar(8) PRIMARY KEY, Name varchar(50), User_name varchar(20) UNIQUE, Platform1 varchar(3) default 'no', Platform2 varchar(3) default 'no', Platform3 varchar(3) default 'no', check (Platform1 in ('yes','no')), check (Platform2 in ('yes','no')), check (Platform3 in ('yes','no')) );")
    cursor.execute("create table if not exists Platform1(S_NO varchar(100) AUTO_INCREMENT PRIMARY KEY, USER_ID varchar(8) REFERENCES USER(ID), QUERY varchar(5000), Response_Suggested varchar(5000), Response_Given varchar(5000));")
    cursor.execute("create table if not exists Platform2(S_NO varchar(100) AUTO_INCREMENT PRIMARY KEY, USER_ID varchar(8) REFERENCES USER(ID), QUERY varchar(5000), Response_Suggested varchar(5000), Response_Given varchar(5000));")
    cursor.execute("create table if not exists Platform3(S_NO varchar(100) AUTO_INCREMENT PRIMARY KEY, USER_ID varchar(8) REFERENCES USER(ID), QUERY varchar(5000), Response_Suggested varchar(5000), Response_Given varchar(5000));") 
    mycon.commit()
    mycon.close()

    print('database made')
makeunib()
    
