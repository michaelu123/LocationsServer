from decimal import Decimal

import sqlalchemy
from flask import Flask, request, jsonify, json
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import MetaData

class DecEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        else:
            return super().default(obj)

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql://testuser:xxx123@raspberrylan/locationsdb'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)
app.json_encoder = DecEncoder

print("SQLAlchemy version", sqlalchemy.__version__)

meta = MetaData()
meta.reflect(bind=db.engine)
dbtables = meta.tables
for tablename in dbtables.keys():
    dbtable = dbtables[tablename]
    for column in dbtable.columns:
        print(tablename, column.name, column.type)

@app.route("/table/<tablename>")
def table(tablename):
    dbtable = dbtables[tablename]
    sel = dbtable.select()
    conn = db.engine.connect()
    r = conn.execute(sel)
    rows = r.fetchall()
    d = dict(rows[0])
    jj = jsonify({"result": [dict(row) for row in rows]})
    return jj

@app.route("/region/<tablename>")
def region(tablename):
    minlat = request.args.get("minlat")
    maxlat = request.args.get("maxlat")
    minlon = request.args.get("minlon")
    maxlon = request.args.get("maxlon")
    conn = db.engine.connect()
    sel = db.text("SELECT * FROM " + tablename +
                  " WHERE lat_round <= :maxlat and lat_round >= :minlat" +
                  " and lon_round <= :maxlon and lon_round >= :minlon" )
    print(sel)
    parms={"minlat": minlat, "maxlat": maxlat, "minlon": minlon, "maxlon": maxlon }
    rows = conn.execute(sel, parms)
    jj = jsonify({"result": [dict(row) for row in rows]})
    return jj


@app.route("/tables")
def tables():
    dbtable = dbtables[tablename]


@app.route("/add/<tablename>", methods=['POST'])
def addRow(tablename):
    print("addtab", tablename)
    j = request.json
    print("json", j)
    dbtable = dbtables[tablename]
    ins = dbtable.insert()
    conn = db.engine.connect()
    r = conn.execute(ins, j)
    return "rows inserted into " + tablename + ": " + str(r.rowcount)

app.run(debug=True)