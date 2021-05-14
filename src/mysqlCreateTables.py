import locale

import mysql.connector
import utils

import config
import secrets

"""
Call this once, manually, to create tables on the raspberry mysql db
The idea is, that the mysql user creator@% creates DBs and tables, but cannot access data,
and that the user locationsuser@localhost can only access data 
"""
# MSSQL types
sqtype = {"int": "INT", "bool": "TINYINT", "prozent": "TINYINT", "string": "VARCHAR(2048)", "float": "DOUBLE"}


# Note: The "on conflict replace" is not available in mysql.

class MySqlCreateTables:
    def getConn(self):
        try:
            mydb = mysql.connector.connect(user='creator', password=secrets.creator_password,
                                           host=secrets.dbhost, database='locationsdb')
        except mysql.connector.Error as err:
            try:
                mydb = mysql.connector.connect(user='creator', password='xxx123',
                                               host='raspberrylan')
                mycursor = mydb.cursor()
                try:
                    mycursor.execute("CREATE DATABASE locationsdb")
                except:
                    pass
                mycursor.execute("GRANT CREATE,DROP,INDEX,ALTER,GRANT OPTION ON locationsdb.* TO 'creator'@'%'")

                # call this as root?
                # mycursor.execute("GRANT SELECT,INSERT,UPDATE,DELETE ON " + self.tabellenname + ".* TO 'locationsuser'@'%'")
                mydb.close()
                mydb = mysql.connector.connect(user='creator', password='xxx123',
                                               host='raspberrylan', database='locationsdb') # ?? self.tabellenname??
            except mysql.connector.Error as err:
                print(err)
                return None
        return mydb

    def initDB(self, baseJS):
        self.colnames = {}

        colnames = ["creator", "created", "modified", "region", "lat", "lon", "lat_round", "lon_round"]
        fields = ["creator VARCHAR(40) NOT NULL", "created DATETIME NOT NULL", "modified DATETIME NOT NULL",
                  "region VARCHAR(20)", "lat DOUBLE NOT NULL", "lon DOUBLE NOT NULL",
                  "lat_round VARCHAR(20) NOT NULL", "lon_round VARCHAR(20) NOT NULL"]
        for feld in self.baseJS.get("daten").get("felder"):
            name = feld.get("name")
            colnames.append(name)
            type = sqtype[feld.get("type")]
            fields.append(name + " " + type)
        fields.append("PRIMARY KEY (creator, lat_round, lon_round)")
        stmt1 = "CREATE TABLE IF NOT EXISTS " + self.tabellenname + "_daten (" + ", ".join(fields) + ")"
        stmt2 = "CREATE INDEX IF NOT EXISTS latlonrnd_daten ON " + self.tabellenname + "_daten (lat_round, lon_round)";

        conn = self.getConn()
        c = conn.cursor()
        c.execute(stmt1)
        c.execute(stmt2)
        self.colnames["daten"] = colnames

        fields = ["creator VARCHAR(40) NOT NULL", "created DATETIME NOT NULL", "region VARCHAR(20)",
                  "lat DOUBLE NOT NULL", "lon DOUBLE NOT NULL",
                  "lat_round VARCHAR(20) NOT NULL", "lon_round VARCHAR(20) NOT NULL",
                  "image_path VARCHAR(256)", "image_url VARCHAR(256)", "bemerkung VARCHAR(256)",
                  "PRIMARY KEY (image_path)"]
        stmt1 = "CREATE TABLE IF NOT EXISTS " + self.tabellenname + "_images (" + ", ".join(fields) + ")"
        stmt2 = "CREATE INDEX IF NOT EXISTS latlonrnd_images ON " + self.tabellenname + "_images (lat_round, lon_round)";
        c = conn.cursor()
        c.execute(stmt1)
        c.execute(stmt2)
        self.colnames["images"] = ["creator", "created", "region", "lat", "lon", "lat_round", "lon_round", "image_path",
                                   "image_url", "bemerkung"]

        if self.baseJS.get("zusatz", None) is None:
            return
        colnames = ["nr", "creator", "created", "modified", "region", "lat", "lon", "lat_round", "lon_round"]
        fields = ["nr INTEGER PRIMARY KEY AUTO_INCREMENT",
                  "creator VARCHAR(40) NOT NULL", "created DATETIME NOT NULL", "modified DATETIME NOT NULL",
                  "region VARCHAR(20)", "lat DOUBLE NOT NULL", "lon DOUBLE NOT NULL",
                  "lat_round VARCHAR(20) NOT NULL", "lon_round VARCHAR(20) NOT NULL"]
        for feld in self.baseJS.get("zusatz").get("felder"):
            name = feld.get("name")
            colnames.append(name)
            type = sqtype[feld.get("type")]
            fields.append(name + " " + type)
        fields.append("UNIQUE(creator, created, modified, lat_round, lon_round)")
        stmt1 = "CREATE TABLE IF NOT EXISTS " + self.tabellenname + "_zusatz (" + ", ".join(fields) + ")"
        stmt2 = "CREATE INDEX IF NOT EXISTS latlonrnd_zusatz ON " + self.tabellenname + "_zusatz (lat_round, lon_round)";
        c = conn.cursor()
        c.execute(stmt1)
        c.execute(stmt2)
        self.colnames["zusatz"] = colnames

    def updateDB(self, baseJS, configs ):
        self.baseJS = baseJS
        self.tabellenname = self.baseJS.get("db_tabellenname")
        bcVers = baseJS["version"];
        dbVers = self.dbVersion()
        if dbVers == 0: # a new table
            self.initDB(baseJS)
            stmt = "CREATE TABLE IF NOT EXISTS versions (tablename VARCHAR(100), version INT)"
            conn = self.getConn()
            c = conn.cursor()
            c.execute(stmt)
            stmt = "INSERT INTO versions (tablename, version) VALUES(%(tablename)s, %(version)s)"
            c.execute(stmt, {'tablename': self.tabellenname, 'version': baseJS["version"]})
            conn.commit()
            return
        if bcVers > dbVers:
            self.updateFields(bcVers, dbVers, configs);


    def dbVersion(self):
        conn = self.getConn()
        c = conn.cursor()
        stmt = "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'locationsdb' AND table_name = %s"
        c.execute(stmt, [self.tabellenname + "_daten"])
        val = c.fetchone()
        if val[0] == 0:
            return 0
        try:
            stmt = "SELECT max(version) FROM versions WHERE tablename = %s"
            c.execute(stmt,[self.tabellenname])
            val = c.fetchone()
            return 1 if val is None or val[0] is None else val[0]
        except Exception as err:
            pass
        return 1

    def updateFields(self, bcVers, dbVers, configs):
        dbConfigArr = [c for c in configs if c["version"] == dbVers]
        if len(dbConfigArr) == 0:
            raise Exception("no config file " + self.tabellenname + "_" + str(dbVers) + " found")
        dbConfig = dbConfigArr[0]
        diffs = self.getDiffs(dbConfig)
        (addedDaten, removedDaten, addedZusatz, removedZusatz) = diffs
        self.addFields(addedDaten, "_daten")
        self.removeFields(removedDaten, "_daten")
        self.addFields(addedZusatz, "_zusatz")
        self.removeFields(removedZusatz, "_zusatz")
        stmt = "UPDATE versions SET version=%(version)s WHERE tablename = %(tablename)s"
        conn = self.getConn()
        c = conn.cursor()
        c.execute(stmt, {'tablename': self.tabellenname, 'version': bcVers})
        conn.commit()
        pass

    def getDiffs(self, oldJS):
        newJS = self.baseJS
        addedDaten = self.inAnotB(newJS["daten"], oldJS["daten"])
        removedDaten = self.inAnotB(oldJS["daten"],newJS["daten"])
        addedZusatz = self.inAnotB(newJS.get("zusatz"), oldJS.get("zusatz"))
        removedZusatz = self.inAnotB(oldJS.get("zusatz"),newJS.get("zusatz"))
        return (addedDaten, removedDaten, addedZusatz, removedZusatz)

    def inAnotB(self, a, b):
        l = []
        la = [] if a is None else a["felder"]
        lb = [] if b is None else b["felder"]
        for am in la:
            found = False
            for bm in lb:
                if am["name"] == bm["name"]:
                    found = True
                    break
            if not found:
                l.append(am)
        return l


    def fieldBefore(self, name, suffix):
        felder = self.baseJS.get(suffix)
        if felder is None:
            return ""
        for (i,f) in enumerate(felder):
            if f["name"] == name:
                if i == 0:
                    return " FIRST"
                return " AFTER " + felder[i-1]["name"]
        return ""


    def addFields(self, addedFields, suffix):
        conn = self.getConn()
        c = conn.cursor()
        for feld in addedFields:
            stmt = "ALTER TABLE " + self.tabellenname + suffix + " ADD " +\
                   feld["name"] + " " + sqtype[feld["type"]] +\
                   self.fieldBefore(feld["name"], suffix[1:])
            c.execute(stmt)
        conn.commit()

    def removeFields(self, removedFields, suffix):
        conn = self.getConn()
        c = conn.cursor()
        for feld in removedFields:
            stmt = "ALTER TABLE " + self.tabellenname + suffix + " DROP " + feld["name"]
            c.execute(stmt)
        conn.commit()

class App:
    def __init__(self):
        self.baseConfig = config.Config()


if __name__ == "__main__":
    try:
        # this seems to have no effect on android for strftime...
        locale.setlocale(locale.LC_ALL, "")
    except Exception as e:
        utils.printEx("setlocale", e)
    app = App()
    db = MySqlCreateTables()
    for name in []: # ["Abstellanlagen", "Abstellplätze", "Alte Bäume", "Nistkästen", "Sitzbänke"]:
        baseJSVersions = app.baseConfig.getBaseVersions(name)
        baseJS = baseJSVersions[0]
        vers = baseJS["version"]
        for bv in baseJSVersions[1:]:
            if bv["version"] > vers:
                baseJS = bv
                vers = bv["version"]
        db.initDB(baseJS)
