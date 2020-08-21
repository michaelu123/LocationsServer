import os
from datetime import datetime
from decimal import Decimal

import sqlalchemy
from flask import Flask, request, jsonify, json, url_for, make_response
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import MetaData

MAX_IMAGE_SIZE = (10*1024*1024)

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
# for tablename in dbtables.keys():
#     dbtable = dbtables[tablename]
#     for column in dbtable.columns:
#         print(tablename, column.name, column.type)

@app.route("/table/<tablename>")
def table(tablename):
    dbtable = dbtables[tablename]
    sel = dbtable.select()
    conn = db.engine.connect()
    r = conn.execute(sel)
    rows = r.fetchall()
    jj = jsonify([dict(row) for row in rows])
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
    jj = jsonify([dict(row) for row in rows])
    return jj

@app.route("/tables")
def tables():
    return jsonify([ str(tablename) for tablename in dbtables.keys()])

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

@app.route("/getimage/<tablename>/<path>")
def getimage(tablename, path):
    datum = path.split("_")[2] # 20200708
    yr = datum[0:4]
    mo = datum[4:6]
    dy = datum[6:8]
    path = os.path.join("images", yr, mo, dy, path)
    with open(path, mode='rb') as imgfile:
        data = imgfile.read()
        resp = make_response(data)
        resp.mimetype = "image/jpeg"
        return resp
    return jsonify({"error": "some error"})

@app.route("/addimage/<tablename>", methods=['POST'])
def addimage(tablename):
    clen = request.content_length
    if clen > MAX_IMAGE_SIZE:
        resp = jsonify({"error": "image too large"})
        resp.status_code = 400
        return resp
    creator = request.args.get("creator")
    created = datetime.fromisoformat(request.args.get("created"))
    lat = float(request.args.get("lat"))
    lon = float(request.args.get("lon"))
    lat_round = request.args.get("lat_round")
    lon_round = request.args.get("lon_round")
    basename = request.args.get("basename")  #48.08551_11.54206_20200708_085657.jpg
    datum = basename.split("_")[2] # 20200708
    yr = datum[0:4]
    mo = datum[4:6]
    dy = datum[6:8]
    data = request.get_data(cache=False)
    path = os.path.join("images", yr, mo, dy)
    os.makedirs(path, exist_ok=True)
    path = os.path.join(path, basename)
    with open(path, mode='wb') as imgfile:
        imgfile.write(data)
    imgurl = request.url_root + url_for('getimage', tablename=tablename, path=basename)
    print("imageurl", imgurl)

    row = { "creator": creator, "created": created, "lat": lat, "lon": lon,
            "lat_round": lat_round, "lon_round": lon_round,
            "image_path": basename, "image_url": imgurl}
    dbtable = dbtables[tablename]
    ins = dbtable.insert()
    conn = db.engine.connect()
    r = conn.execute(ins, row)
    return jsonify({"result": "rows inserted into " + tablename + ": " + str(r.rowcount)})

if __name__ == "__main__":
    print("today", datetime.isoformat(datetime.now()))
    app.run(debug=True)

