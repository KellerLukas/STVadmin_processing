# -*- coding: utf-8 -*-


#import os
import sys
import csv
import datetime








path="/Users/Lukas/Library/CloudStorage/OneDrive-FreigegebeneBibliotheken–TurnvereinWürenlos/Kommunikation - Dokumente/Interne Kommunikation/CleverReach/Adressen/"
patht=path.replace(" ", "\ ")

fin="Kontaktliste/Mitglieder12-2_23.csv"
fout="TVW_List_OUT.csv"
fout_nomail="TVW_List_OUT_nomail.csv"

now = datetime.datetime.now()
curr_date = now.strftime("%d.%m.%Y")


with open(path+fin,"r") as file:
	data=file.readlines()

data = [i.split(";") for i in data[1:] if i]
data = [i for i in data if i[0]]


geschlecht = 1
nachname = 3
vorname = 2
strasse = 4
plz = 5
ort = 6
geb = 7
kat = 8
email = 9
altemail = 10
vereinemail = 11

def calculate_age(geb, stichtag):
	
	stichtag = datetime.datetime.strptime(stichtag,"%d.%m.%Y")
	born = datetime.datetime.strptime(geb,"%d.%m.%Y")

	return stichtag.year - born.year - ((stichtag.month, stichtag.day) < (born.month, born.day))


def create_katlist(kat,sex,geb):
	global dat_gv
	global dat_16m

	katlist = ["Aktive Turner", "Aktive Turnerin", "Passivmitglied", "Kitu (Kinder)", "Mädchen", "Knaben", "Freimitg. Turnend (1)", "Freimitg. nturnend (10)", "Ehrenmitg. nturnend", "Ehrenmitg. turnend", "Männlich", "Weiblich"]
	#Männer = ["Aktive Turner", "Passivmitglied", "Knaben", "Freimitg. Turnend (1)", "Freimitg. nturnend (10)", "Ehrenmitg. nturnend", "Ehrenmitg. turnend"]
	l = []
	for i in range(len(katlist)):#last two are geschlecht
		if i < len(katlist)-2: #last two are sex
			if katlist[i] == kat:
				l.append("YES")
			else:
				l.append("NO")
		else:
			if katlist[i] == sex:
				l.append("YES")
			else:
				l.append("NO")
	return l

def combine_katlists(l1,l2):
	#katlist = ["Aktive Turner", "Aktive Turnerin", "Passivmitglied", "Kitu (Kinder)", "Mädchen", "Knaben", "Freimitg. Turnend (1)", "Freimitg. nturnend (10)", "Ehrenmitg. nturnend", "Ehrenmitg. turnend", "Männlich", "Weiblich"]
	l = []

	if len(l1)!=len(l2):
		sys.exit("aa! errors!")

	for i in range(len(l1)):
		if l1[i] == "YES" or l2[i] == "YES":
			l.append("YES")
		else:
			l.append("NO")
	return(l)

def clean_person(person): #remove \x00 (or \000 in sublime)
	person = [i.rstrip("\x00") for i in person]
	person = [i.rstrip("\n") for i in person]
	person = [i.rstrip("\x00") for i in person]

	return person


def get_abmeldungen():
	with open(path+"Newsletter_abmeldungen.csv","r",encoding='utf-8-sig') as file:
			data=file.readlines()
	
	data = [i.split(";") for i in data if i]
	data = [i for i in data if i[0]] #[mail,vname,nname,date]
	
	#only get email
	data = [i[0] for i in data]
	return data


def get_additional():
	with open(path+"Newsletter_Zusaetzlich.csv","r") as file:
		data=file.readlines()

	data = [i.split(";") for i in data if i]
	data = [i for i in data if i[0]] #[mail,vname,nname,kat,date]
	
	return data



abmeldungen = get_abmeldungen()


outdata = [["Vorname", "Nachname", "Email", "Aktive Turner", "Aktive Turnerin", "Passivmitglied", "Kitu", "Mädchen", "Knaben", "Freimitglied turnend", "Freimitglied nicht turnend", "Ehrenmitglied nicht turnend", "Ehrenmitglied turnend", "Männlich", "Weiblich", "updated"]] #+ "18 an GV" + "Männlich über 16"
seen_mails = []
no_mail = []
for person in data:
	person = clean_person(person)

	if person[email] == "":
		#no_mail.append(person[vorname] + " " + person[nachname])
		if person[altemail] == "":
			if person[vereinemail] == "":
				no_mail.append(person)
				continue
			else:
				person[email]=person[vereinemail]
		else:
			person[email]=person[altemail]


	#check if abgemeldet
	if person[email] in abmeldungen:
		no_mail.append(person)
		#no_mail.append(person[vorname] + " " + person[nachname])
		continue

	if person[email] in seen_mails: #if mail already exists
		
		j = seen_mails.index(person[email]) + 1 #+1 wegen titelzeile

		if outdata[j][2] != person[email]: #check
			sys.exit("aa! errors!")

		outdata[j][0] = outdata[j][0] + " & " + person[vorname]

		if outdata[j][1] == person[nachname]:
			pass
		else:
			outdata[j][1] = outdata[j][1] + " & " + person[nachname]
		#print(person[email])

		l1 =  create_katlist(person[kat],person[geschlecht],person[geb])
		l2 = outdata[j][3:-1]

		outdata[j][3:-1] = combine_katlists(l1,l2)

	else:
		seen_mails.append(person[email])
		
		new_person = [ person[vorname] , person[nachname] , person[email] ]
		#print(person[nachname])
		l = create_katlist( person[kat], person[geschlecht], person[geb] )

		outdata.append(new_person+l+[curr_date])


print(no_mail)

#get additional emails:
add_mails=get_additional()
add_index_mail=0
add_index_vname=1
add_index_nname=2
add_index_kat=3
add_index_geschlecht=5

for person in add_mails:
	person = clean_person(person)
	#check if not already present:
	if person[add_index_mail] in seen_mails:
		print("ERROR: " + person[add_index_mail] + " already in list!!")
		continue
	new_person=[person[add_index_vname],person[add_index_nname],person[add_index_mail]]
	l = create_katlist(person[add_index_kat],person[add_index_geschlecht],[])
	outdata.append(new_person+l+[curr_date])


########
#OUT
########


with open(path+fout,"w",newline='') as file:
	writer = csv.writer(file,delimiter=",")
	writer.writerow(outdata[0])
	writer.writerows(outdata[1:])

with open(path+fout_nomail,"w",newline='') as file:
	writer = csv.writer(file,delimiter=",")
	writer.writerows(no_mail)



