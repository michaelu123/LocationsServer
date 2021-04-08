import locale

import mysql.connector
import utils

from . import config

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
            mydb = mysql.connector.connect(user='creator', password='xxx123',
                                           host='raspberrylan', database='locationsdb')
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
                                               host='raspberrylan', database=self.tabellenname)
            except mysql.connector.Error as err:
                print(err)
                return None
        return mydb

    def initDB(self, baseJS):
        self.baseJS = baseJS
        self.aliasname = None
        self.tabellenname = self.baseJS.get("db_tabellenname")
        self.stellen = self.baseJS.get("gps").get("nachkommastellen")
        self.colnames = {}
        db = utils.getDataDir() + "/" + self.baseJS.get("db_name")

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
        baseJS = app.baseConfig.getBase(name)
        db.initDB(baseJS)
