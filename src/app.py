import io
import os
from datetime import datetime
from decimal import Decimal

import sqlalchemy
from PIL import Image
from flask import Flask, request, jsonify, json, url_for, make_response
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import MetaData
from sqlalchemy.exc import IntegrityError

from . import config
from . import utils
from .mysqlCreateTables import MySqlCreateTables

MAX_IMAGE_SIZE = (10 * 1024 * 1024)
MAX_CONFIG_SIZE = (10 * 1024)


class DecEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        elif isinstance(obj, datetime):
            return obj.strftime("%Y.%m.%d %H:%M:%S")
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
    with db.engine.connect() as conn:
        r = conn.execute(sel)
        rows = r.fetchall()
    jj = jsonify([list(row) for row in rows])
    return jj


@app.route("/region/<tablename>")
def region(tablename):
    minlat = request.args.get("minlat")
    maxlat = request.args.get("maxlat")
    minlon = request.args.get("minlon")
    maxlon = request.args.get("maxlon")
    region = request.args.get("region")
    with db.engine.connect() as conn:
        sel = "SELECT * FROM " + tablename + " WHERE lat_round <= :maxlat and lat_round >= :minlat and lon_round <= :maxlon and lon_round >= :minlon"
        if region is not None and region != "":
            sel += " and region = :region"
        # print(sel)
        sel = db.text(sel)
        parms = {"minlat": minlat, "maxlat": maxlat, "minlon": minlon, "maxlon": maxlon, "region": region}
        rows = conn.execute(sel, parms)
    jj = jsonify([list(row) for row in rows])
    return jj


@app.route("/tables")
def tables():
    return jsonify([str(tablename) for tablename in dbtables.keys()])


@app.route("/add/<tablename>", methods=['POST'])
def addRow(tablename):
    # print("addtab", tablename)
    jlist = request.json
    # print("json", jlist)
    dbtable = dbtables[tablename]
    ins = dbtable.insert()
    with db.engine.connect() as conn:
        # try to achieve what sqlite does with "on conflict replace"
        for retries in range(2):
            try:
                r = conn.execute(ins, jlist)
                break
            except IntegrityError as e:
                if retries == 0:
                    nrRows = 0
                    for jrow in jlist:
                        if tablename.endswith("_daten"):
                            # PRIMARY KEY(lat_round, lon_round)
                            creator = jrow["creator"]
                            lat_round = jrow["lat_round"]
                            lon_round = jrow["lon_round"]
                            delStmt = db.text("DELETE FROM " + tablename +
                                              " WHERE creator = :creator and lat_round = :lat_round and lon_round = :lon_round")
                            parms = {"creator": creator, "lat_round": lat_round, "lon_round": lon_round}
                        elif tablename.endswith("_images"):
                            # PRIMARY KEY(image_path)
                            image_path = jrow["image_path"]
                            delStmt = db.text("DELETE FROM " + tablename +
                                              " WHERE image_path = :image_path")
                            parms = {"image_path": image_path}
                        elif tablename.endswith("_zusatz"):
                            # UNIQUE(creator, created, modified, lat_round, lon_round)
                            creator = jrow["creator"]
                            created = jrow["created"]
                            modified = jrow["modified"]
                            lat_round = jrow["lat_round"]
                            lon_round = jrow["lon_round"]
                            delStmt = db.text("DELETE FROM " + tablename +
                                              " WHERE creator = :creator and created = :created and "
                                              "modified = :modified and lat_round = :lat_round and lon_round = :lon_round")
                            parms = {"creator": creator, "created": created, "modified": modified,
                                     "lat_round": lat_round, "lon_round": lon_round}
                        else:
                            raise ValueError("Unbekannter Tabellenname " + tablename)
                        r = conn.execute(delStmt, parms)
                        nrRows += r.rowcount
                    print("rows deleted from " + tablename + ": " + str(nrRows))
                    continue
                else:
                    print("addRow exception", e)
                    raise (e)
        print("rows inserted into " + tablename + ": " + str(r.rowcount))
        return jsonify({tablename: r.rowcount})


@app.route("/getimage/<tablename>/<path>")
def getimage(tablename, path):
    maxdim = request.args.get("maxdim")
    maxdim = 0 if maxdim is None else int(maxdim)
    datum = path.split("_")[2]  # 20200708
    yr = datum[0:4]
    mo = datum[4:6]
    dy = datum[6:8]
    path = os.path.join("images", yr, mo, dy, path)
    img = Image.open(path)
    iw = img.width
    ih = img.height
    if maxdim != 0:
        xw = iw / maxdim
        xh = ih / maxdim
        x = xh if xw < xh else xw
        w = int(iw / x)
        h = int(ih / x)
        img = img.resize(size=(w, h))
    buf = io.BytesIO()
    img.save(buf, format="jpeg")
    resp = make_response(buf.getvalue())
    resp.mimetype = "image/jpeg"
    return resp


@app.route("/addimage/<tablename>/<basename>", methods=['POST'])
def addimage(tablename, basename):
    clen = request.content_length
    if clen > MAX_IMAGE_SIZE:
        resp = jsonify({"error": "image too large"})
        resp.status_code = 400
        return resp
    datum = basename.split("_")[2]  # 20200708
    yr = datum[0:4]
    mo = datum[4:6]
    dy = datum[6:8]
    data = request.get_data(cache=False)
    path = os.path.join("images", yr, mo, dy)
    os.makedirs(path, exist_ok=True)
    path = os.path.join(path, basename)
    with open(path, mode='wb') as imgfile:
        imgfile.write(data)
    imgurl = request.url_root[0:-1] + url_for('getimage', tablename=tablename, path=basename)
    return jsonify({"url": imgurl})


@app.route("/addconfig", methods=['POST'])
def addconfig():
    clen = request.content_length
    if clen > MAX_CONFIG_SIZE:
        resp = jsonify({"error": "config file too large"})
        resp.status_code = 400
        return resp
    baseConfig = config.Config()
    data = request.get_data(cache=False)
    confJS = baseConfig.addConfig(io.BytesIO(data))
    if confJS is None:
        return jsonify("Error", baseConfig.errors)
    name = utils.normalize(confJS["name"])
    if name is None or name == "" or len(name) > 100:
        return jsonify("Error", "invalid name:" + name)
    path = os.path.join("config", name + ".json")
    if os.path.exists(path):
        return jsonify("Error", "File " + name + ".json already exists")
    db = MySqlCreateTables()
    db.initDB(confJS)
    with open(path, mode='wb', encoding="UTF-8") as configFile:
        configFile.write(data)
    return jsonify({"name": name})


@app.route("/configs")
def getConfigs():
    return jsonify(sorted(os.listdir("config")))


@app.route("/config/<name>")
def getConfig(name):
    path = os.path.join("config", name)
    with open(path, "r", encoding="UTF-8") as jsonFile:
        return json.load(jsonFile)


if __name__ == "__main__":
    print("today", datetime.isoformat(datetime.now()))
    app.run(debug=True, use_reloader=False, host="0.0.0.0")

# http://raspberrylan.1qgrvqjevtodmryr.myfritz.net:8080/
