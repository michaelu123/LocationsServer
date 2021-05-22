import base64
import http
import io
import os
from datetime import datetime
from decimal import Decimal

import sqlalchemy
from PIL import Image
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PublicKey, X25519PrivateKey
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7
from cryptography.hazmat.primitives.hashes import Hash,SHA256
from flask import Flask, request, jsonify, json, url_for, make_response
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import MetaData
from sqlalchemy.exc import IntegrityError

import config
import secrets
import utils
from mysqlCreateTables import MySqlCreateTables

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
app.config['SQLALCHEMY_DATABASE_URI'] = secrets.dburl
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)
app.json_encoder = DecEncoder

print("SQLAlchemy version", sqlalchemy.__version__)
meta = MetaData()
meta.reflect(bind=db.engine)
dbtables = meta.tables

sharedKeys = {}
loginDates = {}
usernames = {}
passwords = {}


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
        sel = "SELECT * FROM " + tablename + \
              " WHERE lat_round <= :maxlat and lat_round >= :minlat and lon_round <= :maxlon and lon_round >= :minlon"
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
    # print("addRow", tablename)
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
                                              " WHERE creator = :creator and lat_round = :lat_round and lon_round = "
                                              ":lon_round")
                            parms = {"creator": creator, "lat_round": lat_round, "lon_round": lon_round}
                        elif tablename.endswith("_images"):
                            # PRIMARY KEY(image_path)
                            image_path = jrow["image_path"]
                            delStmt = db.text("DELETE FROM " + tablename +
                                              " WHERE image_path = :image_path")
                            parms = {"image_path": image_path}
                        elif tablename.endswith("_zusatz"):
                            err = str(e)
                            if err.index("'PRIMARY'") > 0:
                                # primary key pk
                                nr = jrow["nr"]
                                delStmt = db.text("DELETE FROM " + tablename +
                                                  " WHERE nr = :nr")
                                parms = {"nr": nr}
                            else:
                                # UNIQUE(creator, created, modified, lat_round, lon_round)
                                creator = jrow["creator"]
                                created = jrow["created"]
                                modified = jrow["modified"]
                                lat_round = jrow["lat_round"]
                                lon_round = jrow["lon_round"]
                                delStmt = db.text("DELETE FROM " + tablename +
                                                  " WHERE creator = :creator and created = :created and "
                                                  "modified = :modified and lat_round = :lat_round and lon_round = "
                                                  ":lon_round")
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
        return jsonify({tablename: r.rowcount, "rowid": r.lastrowid })

@app.route("/official/<tablename>", methods=['POST'])
def official(tablename):
    print("official", tablename)
    jrow = request.json
    print("json", jrow)
    dbtable = dbtables[tablename]
    ins = dbtable.insert()
    with db.engine.begin() as conn:
        lat_round = jrow["lat_round"]
        lon_round = jrow["lon_round"]
        delStmt = db.text("DELETE FROM " + tablename +
                          " WHERE lat_round = :lat_round and lon_round = :lon_round")
        parms = {"lat_round": lat_round, "lon_round": lon_round}
        r = conn.execute(delStmt, parms)
        print("official deleted " + str(r.rowcount))
        ins = dbtable.insert()
        r = conn.execute(ins, jrow)
        print("official inserted " + str(r.rowcount))
    return jsonify({tablename: r.rowcount})

@app.route("/deleteloc/<tablebase>", methods=['DELETE'])
def deleteloc(tablebase):
    res = {}
    hasZusatz = request.args.get("haszusatz") == "true"
    lat_round = request.args.get("lat")
    lon_round = request.args.get("lon")
    tables = ["daten", "images"]
    if hasZusatz:
        tables.append("zusatz")
    with db.engine.begin() as conn:
        for table in tables:
            delStmt = db.text("DELETE FROM " + tablebase + "_" + table +
                          " WHERE lat_round = :lat_round and lon_round = :lon_round")
            parms = {"lat_round": lat_round, "lon_round": lon_round}
            r = conn.execute(delStmt, parms)
            res[table] = r.rowcount
    return jsonify(res)

@app.route("/getimage/<tablebase>/<path>")
def getimage(tablebase, path):
    if tablebase.endswith("_images"):
        tablebase = tablebase[0:-7]
    maxdim = request.args.get("maxdim")
    maxdim = 0 if maxdim is None else int(maxdim)
    datum = path.split("_")[2]  # 20200708
    yr = datum[0:4]
    mo = datum[4:6]
    dy = datum[6:8]
    path = os.path.join("images", tablebase, yr, mo, dy, path)
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

@app.route("/deleteimage/<tablebase>/<path>", methods=['DELETE'])
def deleteimage(tablebase, path):
    if tablebase.endswith("_images"):
        tablebase = tablebase[0:-7]
    datum = path.split("_")[2]  # 20200708
    yr = datum[0:4]
    mo = datum[4:6]
    dy = datum[6:8]
    path = os.path.join("images", tablebase, yr, mo, dy, path)
    os.remove(path)
    return jsonify({})


@app.route("/addimage/<tablebase>/<imgname>", methods=['POST'])
def addimage(tablebase, imgname):
    if tablebase.endswith("_images"):
        tablebase = tablebase[0:-7]
    clen = request.content_length
    if clen > MAX_IMAGE_SIZE:
        resp = jsonify({"error": "image too large"})
        resp.status_code = 400
        return resp
    datum = imgname.split("_")[2]  # 20200708
    yr = datum[0:4]
    mo = datum[4:6]
    dy = datum[6:8]
    data = request.get_data(cache=False)
    path = os.path.join("images", tablebase, yr, mo, dy)
    os.makedirs(path, exist_ok=True)
    path = os.path.join(path, imgname)
    with open(path, mode='wb') as imgfile:
        imgfile.write(data)
    imgurl = request.url_root[0:-1] + url_for('getimage', tablebase=tablebase, path=path)
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
    confJS = baseConfig.checkConfig(io.BytesIO(data))
    if confJS is None:
        return jsonify("Error", baseConfig.errors)
    name = utils.normalize(confJS["name"])
    if name is None or name == "" or len(name) > 100:
        return jsonify("Error", "invalid name:" + name)
    nameVers = name + "_" + str(confJS["version"])
    path = os.path.join("config", nameVers + ".json")
    if os.path.exists(path):
        return jsonify("Error", "File " + os.path.abspath(path) + " already exists")
    db = MySqlCreateTables()
    db.updateDB(confJS, baseConfig.getBaseVersions(name))
    with open(path, mode='wb') as configFile:
        configFile.write(data)
    baseConfig.addConfig(confJS)
    return jsonify({"name": name})


@app.route("/configs")
def getConfigs():
    return jsonify(sorted(os.listdir("config")))


@app.route("/config/<name>")
def getConfig(name):
    path = os.path.join("config", name)
    with open(path, "r", encoding="UTF-8") as jsonFile:
        return json.load(jsonFile)


@app.route("/markercodes/<tablebase>")
def getMarkerCodes(tablebase):
    path = os.path.join("markercodes", tablebase)
    if not os.path.exists(path):
        return jsonify([])
    filenames = sorted(os.listdir(path))
    filenames = [ filename[0:-5] for filename in filenames if filename.endswith(".json")]
    return jsonify(filenames)


@app.route("/markercode/<tablebase>/<name>")
def getMarkerCode(tablebase, name):
    path = os.path.join("markercodes", tablebase, name + ".json")
    with open(path, "r", encoding="UTF-8") as f:
        codeJS = f.read()
        return codeJS


@app.route("/addmarkercode/<tablebase>/<name>", methods=['POST'])
def addMarkerCode(tablebase, name):
    clen = request.content_length
    if clen > 2000:
        resp = jsonify({"error": "markercode file too large"})
        resp.status_code = 400
        return resp
    data = request.get_data(cache=False)
    name = utils.normalize(name)
    if name is None or name == "" or len(name) > 100:
        return jsonify("Error", "invalid name:" + name)
    path = os.path.join("markercodes", tablebase)
    os.makedirs(path, exist_ok=True)
    path = os.path.join(path, name + ".json")
    with open(path, mode='wb') as markerCodeFile:
        markerCodeFile.write(data)
    return jsonify({"name": name})

@app.route("/deletemarkercode/<tablebase>/<name>", methods=['DELETE'])
def deletemarkercode(tablebase, name):
    path = os.path.join("markercodes", tablebase, name + ".json")
    os.remove(path)
    return jsonify({})

@app.route("/kex", methods=['POST'])
def kex():
    clen = request.content_length
    if clen > 1000:
        resp = jsonify({"error": "config file too large"})
        resp.status_code = 400
        return resp
    data = request.json
    pubBytes = base64.b64decode(data["pubkey"])
    id = data["id"]
    his_pubkey = X25519PublicKey.from_public_bytes(pubBytes)
    my_privkey = X25519PrivateKey.generate()
    my_pubkey = my_privkey.public_key()
    sharedkey = my_privkey.exchange(his_pubkey)
    sharedKeys[id] = sharedkey
    print("sharedkey", base64.b64encode(sharedkey).decode("utf-8"))
    my_pkbytes = my_pubkey.public_bytes(encoding=serialization.Encoding.Raw,
      format=serialization.PublicFormat.Raw)
    my_pkS = base64.b64encode(my_pkbytes).decode("utf-8")
    return jsonify({"pubkey": my_pkS})

@app.route("/test", methods=['POST'])
def test():
    clen = request.content_length
    if clen > 1000:
        resp = jsonify({"error": "config file too large"})
        resp.status_code = 400
        return resp
    data = request.json
    id = data["id"]
    encData = base64.b64decode(data["enc"])
    iv = base64.b64decode(data["iv"])
    sharedkey = sharedKeys[id]
    aesAlg = algorithms.AES(sharedkey)
    cipher = Cipher(aesAlg, modes.CBC(iv))
    decryptor = cipher.decryptor()
    decData = decryptor.update(encData) + decryptor.finalize()
    unpadder = PKCS7(128).unpadder()
    decData = unpadder.update(decData) +unpadder.finalize()
    decData = decData.decode("utf-8")
    print("decData", decData)
    return jsonify({"res": decData})
    pass

@app.route("/auth/<loginOrSignon>", methods=['POST'])
def auth(loginOrSignon):
    try:
        login = loginOrSignon == "login"
        clen = request.content_length
        if clen > 1000:
            resp = jsonify({"error": "req too large"})
            resp.status_code = 400
            return resp
        data = request.json
        id = data["id"]
        encData = base64.b64decode(data["ctxt"])
        iv = base64.b64decode(data["iv"])
        sharedkey = sharedKeys[id]
        aesAlg = algorithms.AES(sharedkey)
        cipher = Cipher(aesAlg, modes.CBC(iv))
        decryptor = cipher.decryptor()
        decDataDec = decryptor.update(encData) + decryptor.finalize()
        unpadder = PKCS7(128).unpadder()
        decDataB = unpadder.update(decDataDec) +unpadder.finalize()
        decDataS = decDataB.decode("utf-8")
        credMsgJS = json.JSONDecoder().decode(decDataS)
        print("cred", credMsgJS)
        digest = Hash(SHA256())
        concatS = credMsgJS["password"] + ":" + credMsgJS["email"]
        concatB = concatS.encode("utf-8")
        digest.update(concatB)
        concatHash = digest.finalize()
        if login:
            username = usernames.get(concatS)
            storedHash = passwords.get(concatS)
            if  username is None or storedHash is None or storedHash != concatHash:
                resp = jsonify({"Auth error"})
                resp.status_code = http.HTTPStatus.UNAUTHORIZED
                return resp
        else:
            username = credMsgJS["username"]
            passwords[concatS] = concatHash
            usernames[concatS] = username
        loginDates[id] = datetime.now()
        return jsonify({"id": id, "username": username})
    except Exception as ex:
        resp = jsonify({"error": str(ex)})
        resp.status_code = 400
        return resp


if __name__ == "__main__":
    print("today", datetime.isoformat(datetime.now()))
    app.run(debug=True, use_reloader=False, host="0.0.0.0")

# http://raspberrylan.1qgrvqjevtodmryr.myfritz.net:8080/
