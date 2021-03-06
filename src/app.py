import base64
import http
import io
import os
from datetime import datetime
from decimal import Decimal
from functools import wraps

import sqlalchemy
from PIL import Image
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PublicKey, X25519PrivateKey
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.hashes import Hash, SHA256
from cryptography.hazmat.primitives.padding import PKCS7
from flask import Flask, request, jsonify, json, url_for, make_response
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import MetaData
from sqlalchemy.exc import IntegrityError

import config
import fb
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
fb.init(app)

id2sharedKey = {}  # id -> secretKey
id2loginDate = {}  # id -> datetime
id2username = {}  # id -> username


# for tablename in dbtables.keys():
#     dbtable = dbtables[tablename]
#     for column in dbtable.columns:
#         print(tablename, column.name, column.type)

def expiration(id2):
    loggedIn = id2loginDate[id2]
    now = datetime.now()
    diff = int((now - loggedIn).total_seconds())
    # print("diff", diff) # test exoiration
    # if diff % 5 == 0:
    #     return "SOON"
    diff = diff / (24 * 60 * 60)
    if diff < 12:
        return "OK"
    if diff < 24:
        return "SOON"
    return None


def verifyToken(token, mustBeAdmin):
    if token is None:
        return None, None
    tokenB = base64.b64decode(token)
    tokenS = tokenB.decode("utf-8")
    tokenJS = json.JSONDecoder().decode(tokenS)
    id2 = tokenJS["id"]
    nowS = tokenJS["now"]
    sharedkey = id2sharedKey.get(id2)
    if sharedkey is None:
        return None, None
    username = id2username.get(id2)
    if username is None:
        return None, None
    if mustBeAdmin and username != "admin":
        return None, None
    nowEnc = base64.b64decode(tokenJS["nowEnc"])
    ivS = tokenJS["iv"]
    ivB = base64.b64decode(ivS)
    aesAlg = algorithms.AES(sharedkey)
    cipher = Cipher(aesAlg, modes.CBC(ivB))
    decryptor = cipher.decryptor()
    nowDecB = decryptor.update(nowEnc) + decryptor.finalize()
    unpadder = PKCS7(128).unpadder()
    nowDecB = unpadder.update(nowDecB) + unpadder.finalize()
    nowDecS = nowDecB.decode("utf-8")
    if nowS != nowDecS:  # so sharedKey was not working
        return None, None
    now = datetime.utcnow()
    clntNow = datetime.utcfromtimestamp(int(nowS) / 1000)
    diff = int((now - clntNow).total_seconds())
    if -600 < diff < 600: # clntNow within 10 minutes before or after now
        return expiration(id2), username
    return None, None


# see https://www.artima.com/weblogs/viewpost.jsp?thread=240845#decorator-functions-with-decorator-arguments
def tokencheck(mustBeAdmin):
    def wrap(f):
        @wraps(f)
        def tcdecorator(*args, **kwargs):
            (respHdr, username) = verifyToken(request.headers.get("x-auth"), mustBeAdmin)
            if respHdr is None:
                resp = make_response("Auth error", 401)
                return resp
            resp = f(*args, **kwargs, username=username)
            resp.headers['x-auth'] = respHdr
            return resp

        return tcdecorator

    return wrap


@app.route("/checktoken")
@tokencheck(False)
def checkToken(**_):  # check if token is still valid
    return jsonify({"token":"ok"})


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
@tokencheck(False)
def region(tablename, **_):
    minlat = request.args.get("minlat")
    maxlat = request.args.get("maxlat")
    minlon = request.args.get("minlon")
    maxlon = request.args.get("maxlon")
    region2 = request.args.get("region")
    with db.engine.connect() as conn:
        sel = "SELECT * FROM " + tablename + \
              " WHERE lat_round <= :maxlat and lat_round >= :minlat and lon_round <= :maxlon and lon_round >= :minlon"
        if region2 is not None and region2 != "":
            sel += " and region = :region"
        # print(sel)
        sel = db.text(sel)
        parms = {"minlat": minlat, "maxlat": maxlat, "minlon": minlon, "maxlon": maxlon, "region": region2}
        rows = conn.execute(sel, parms)
    jj = jsonify([list(row) for row in rows])
    return jj


@app.route("/tables")
def tables():
    return jsonify([str(tablename) for tablename in dbtables.keys()])


@app.route("/add/<tablename>", methods=['POST'])
@tokencheck(False)
def addRow(tablename, username=None):
    # print("addRow", tablename)
    jlist = request.json
    if username is not None and username != "admin":
        for row in jlist:
            row["creator"] = username
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
                    raise e
        print("rows inserted into " + tablename + ": " + str(r.rowcount))
        resp = jsonify({tablename: r.rowcount, "rowid": r.lastrowid})
        return resp


@app.route("/official/<tablename>", methods=['POST'])
@tokencheck(True)
def official(tablename, **_):
    jrow = request.json
    dbtable = dbtables[tablename]
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
@tokencheck(True)
def deleteLoc(tablebase, **_):
    res = {}
    hasZusatz = request.args.get("haszusatz") == "true"
    lat_round = request.args.get("lat")
    lon_round = request.args.get("lon")
    tables2 = ["daten", "images"]
    if hasZusatz:
        tables2.append("zusatz")
    with db.engine.begin() as conn:
        for table2 in tables2:
            delStmt = db.text("DELETE FROM " + tablebase + "_" + table2 +
                              " WHERE lat_round = :lat_round and lon_round = :lon_round")
            parms = {"lat_round": lat_round, "lon_round": lon_round}
            r = conn.execute(delStmt, parms)
            res[table2] = r.rowcount
    return jsonify(res)


@app.route("/getimage/<tablebase>/<path>")
def getImage(tablebase, path):
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
@tokencheck(True)
def deleteImage(tablebase, path, **_):
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
@tokencheck(False)
def addImage(tablebase, imgname, **_):
    if tablebase.endswith("_images"):
        tablebase = tablebase[0:-7]
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
@tokencheck(True)
def addConfig(**_):
    baseConfig = config.Config()
    data = request.get_data(cache=False)
    confJS = baseConfig.checkConfig(io.BytesIO(data))
    if confJS is None:
        return jsonify("Error", baseConfig.errors)
    name = utils.normalize(confJS["name"])
    if name is None or name == "" or len(name) > 100:
        return jsonify("Error", "invalid name:" + str(name))
    nameVers = name + "_" + str(confJS["version"])
    path = os.path.join("config", nameVers + ".json")
    if os.path.exists(path):
        return jsonify("Error", "File " + os.path.abspath(path) + " already exists")
    db2 = MySqlCreateTables()
    db2.updateDB(confJS, baseConfig.getBaseVersions(name))
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
    filenames = [filename[0:-5] for filename in filenames if filename.endswith(".json")]
    return jsonify(filenames)


@app.route("/markercode/<tablebase>/<name>")
def getMarkerCode(tablebase, name):
    path = os.path.join("markercodes", tablebase, name + ".json")
    with open(path, "r", encoding="UTF-8") as f:
        codeJS = f.read()
        return codeJS


@app.route("/addmarkercode/<tablebase>/<name>", methods=['POST'])
@tokencheck(True)
def addMarkerCode(tablebase, name, **_):
    data = request.get_data(cache=False)
    name = utils.normalize(name)
    if name is None or name == "" or len(name) > 100:
        return jsonify("Error", "invalid name:" + str(name))
    path = os.path.join("markercodes", tablebase)
    os.makedirs(path, exist_ok=True)
    path = os.path.join(path, name + ".json")
    with open(path, mode='wb') as markerCodeFile:
        markerCodeFile.write(data)
    return jsonify({"name": name})


@app.route("/deletemarkercode/<tablebase>/<name>", methods=['DELETE'])
@tokencheck(True)
def deleteMarkerCode(tablebase, name, **_):
    path = os.path.join("markercodes", tablebase, name + ".json")
    os.remove(path)
    return jsonify({})


@app.route("/kex", methods=['POST'])
def kex():  # Diffie Hellman key exchange X25519
    data = request.json
    pubBytes = base64.b64decode(data["pubkey"])
    id2 = data["id"]
    his_pubkey = X25519PublicKey.from_public_bytes(pubBytes)
    my_privkey = X25519PrivateKey.generate()
    my_pubkey = my_privkey.public_key()
    sharedkey = my_privkey.exchange(his_pubkey)
    id2sharedKey[id2] = sharedkey
    my_pkbytes = my_pubkey.public_bytes(encoding=serialization.Encoding.Raw,
                                        format=serialization.PublicFormat.Raw)
    my_pkS = base64.b64encode(my_pkbytes).decode("utf-8")
    return jsonify({"pubkey": my_pkS})


@app.route("/test", methods=['POST'])
def test():
    data = request.json
    id2 = data["id"]
    encData = base64.b64decode(data["enc"])
    iv = base64.b64decode(data["iv"])
    sharedkey = id2sharedKey[id2]
    aesAlg = algorithms.AES(sharedkey)
    cipher = Cipher(aesAlg, modes.CBC(iv))
    decryptor = cipher.decryptor()
    decData = decryptor.update(encData) + decryptor.finalize()
    unpadder = PKCS7(128).unpadder()
    decData = unpadder.update(decData) + unpadder.finalize()
    decData = decData.decode("utf-8")
    return jsonify({"res": decData})
    pass


def userFromDB(emailS):
    with db.engine.connect() as conn:
        sel = "SELECT username, encpw FROM users WHERE email = :email"
        sel = db.text(sel)
        parms = {"email": emailS}
        res = conn.execute(sel, parms)
        if res.rowcount != 1:
            return None, None
        row = res.fetchone()
        username = row[0]
        encPWS = row[1]
        encPWB = base64.b64decode(encPWS)
        return username, encPWB


def userToDB(emailS, username, storedHash):
    encPWS = base64.b64encode(storedHash).decode("utf-8")
    with db.engine.connect() as conn:
        ins = "INSERT into users(email, username, encpw) VALUES(:email, :username, :encpw)"
        ins = db.text(ins)
        parms = {"email": emailS, "username": username, "encpw": encPWS}
        conn.execute(ins, parms)


def dbContainsUsername(username):
    with db.engine.connect() as conn:
        sel = "SELECT username FROM users WHERE username = :username"
        sel = db.text(sel)
        parms = {"username": username}
        res = conn.execute(sel, parms)
        return res.rowcount > 0


@app.route("/auth/<loginOrSignon>", methods=['POST'])
def auth(loginOrSignon):
    try:
        login = loginOrSignon == "login"
        data = request.json
        id2 = data["id"]
        encData = base64.b64decode(data["ctxt"])
        iv = base64.b64decode(data["iv"])
        sharedkey = id2sharedKey[id2]
        aesAlg = algorithms.AES(sharedkey)
        cipher = Cipher(aesAlg, modes.CBC(iv))
        decryptor = cipher.decryptor()
        decDataDec = decryptor.update(encData) + decryptor.finalize()
        unpadder = PKCS7(128).unpadder()
        decDataB = unpadder.update(decDataDec) + unpadder.finalize()
        decDataS = decDataB.decode("utf-8")
        credMsgJS = json.JSONDecoder().decode(decDataS)
        digest = Hash(SHA256())
        emailS = credMsgJS["email"]
        concatS = credMsgJS["password"] + ":" + emailS
        concatB = concatS.encode("utf-8")
        digest.update(concatB)
        concatHash = digest.finalize()

        (username, storedHash) = userFromDB(emailS)
        if storedHash is None or storedHash != concatHash:
            if login:
                resp = jsonify({"Auth error": "unknown user or bad password"})
                resp.status_code = http.HTTPStatus.UNAUTHORIZED
                return resp
            else:
                username2 = credMsgJS["username"]
                if dbContainsUsername(username2):
                    resp = jsonify({"Auth error": "user name already in use"})
                    resp.status_code = http.HTTPStatus.UNAUTHORIZED
                    return resp
                userToDB(emailS, username2, concatHash)
                username = username2
        else:
            if not login:
                username2 = credMsgJS["username"]
                if username != username2:
                    resp = jsonify({"Auth error": "user name can not be changed"})
                    resp.status_code = http.HTTPStatus.UNAUTHORIZED
                    return resp
        id2loginDate[id2] = datetime.now()
        id2username[id2] = username
        return jsonify({"id": id2, "username": username})
    except Exception as ex:
        resp = jsonify({"error": str(ex)})
        resp.status_code = 401
        return resp


if __name__ == "__main__":
    print("today", datetime.isoformat(datetime.now()))
    app.run(debug=True, use_reloader=False, host="0.0.0.0")

# http://raspberrylan.1qgrvqjevtodmryr.myfritz.net:8080/
