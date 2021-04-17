import glob
import json

import utils

syntax = \
    {
        "name": {
            "required": True,
            "type": "string"
        },
        "db_name": {
            "required": True,
            "type": "string"
        },
        "db_tabellenname": {
            "required": True,
            "type": "string"
        },
        "protected": {
            "required": False,
            "type": "bool"
        },
        "gps": {
            "required": True,
            "type": {
                "nachkommastellen": {
                    "required": True,
                    "type": "int"
                },
                "min_zoom": {
                    "required": True,
                    "type": "int"
                }
            }
        },
        "daten": {
            "required": True,
            "type": {
                "protected": {
                    "required": False,
                    "type": "bool"
                },
                "felder": {
                    "required": True,
                    "type": "array",
                    "elem": {
                        "name": {
                            "required": True,
                            "type": "string"
                        },
                        "hint_text": {
                            "required": True,
                            "type": "string"
                        },
                        "helper_text": {
                            "required": True,
                            "type": "string"
                        },
                        "type": {
                            "required": True,
                            "type": "auswahl",
                            "auswahl": [
                                "string",
                                "bool",
                                "int",
                                "float",
                                "prozent"
                            ]
                        },
                        "limited": {
                            "required": False,
                            "type": "array",
                            "elem": "string"
                        },
                        "required": {
                            "required": False,
                            "type": "bool"
                        }
                    }
                }
            }
        },
        "zusatz": {
            "required": False,
            "type": {
                "protected": {
                    "required": False,
                    "type": "bool"
                },
                "felder": {
                    "required": True,
                    "type": "array",
                    "elem": {
                        "name": {
                            "required": True,
                            "type": "string"
                        },
                        "hint_text": {
                            "required": True,
                            "type": "string"
                        },
                        "helper_text": {
                            "required": True,
                            "type": "string"
                        },
                        "type": {
                            "required": True,
                            "type": "auswahl",
                            "auswahl": [
                                "string",
                                "bool",
                                "int",
                                "float",
                                "prozent"
                            ]
                        },
                        "limited": {
                            "required": False,
                            "type": "array",
                            "elem": "string"
                        },
                        "required": {
                            "required": False,
                            "type": "bool"
                        }
                    }
                }
            }
        }
    }


class Config():
    def __init__(self):
        configDir = utils.getDataDir()
        self.configs = {}
        self.errors = []
        for dir in set([configDir, "."]):
            self.file_list = sorted(glob.glob(dir + "/config/*.json"))
            for f in self.file_list:
                try:
                    with open(f, "r", encoding="UTF-8") as jsonFile:
                        confJS = json.load(jsonFile)
                        try:
                            self.checkSyntax(confJS, syntax)
                        except Exception as e:
                            utils.printEx("Kann Datei " + f + " nicht parsen:", e)
                            self.errors.append("Kann Datei " + f + " nicht parsen:" + str(e))
                            continue
                        nm = confJS.get("name")
                        l = self.configs.get(nm)
                        if l is None:
                            l = []
                            self.configs[nm] = l
                        l.append(confJS)
                        print("gelesen:", f, nm)
                except Exception as e:
                    utils.printEx("Fehler beim Lesen von " + f, e)


    def checkConfig(self, data):
        confJS = json.load(data)
        try:
            self.checkSyntax(confJS, syntax)
        except Exception as e:
            utils.printEx("Kann neue Config-Daten nicht parsen:", e)
            self.errors.append("Kann neue Config-Daten nicht parsen:" + str(e))
            return None
        return confJS


    def addConfig(self, confJS):
        nm = confJS.get("name")
        l = self.configs.get(nm)
        if l is None:
            l = []
            self.configs[nm] = l
        l.append(confJS)


    def getNames(self):
        return list(self.configs.keys())

    def getBaseVersions(self, name):
        return self.configs.get(name,  [])

    def checkSyntax(self, js, syn):
        for synkey in syn.keys():
            required = syn.get(synkey).get("required")
            # print("checksyntax", "key:", synkey, "req:", required)
            if synkey in js.keys():
                self.checkType(synkey, syn.get(synkey), js.get(synkey))
            elif required:
                raise (ValueError(synkey + " wurde nicht spezifiziert"))

    def checkType(self, key, syn, js):
        syntype = syn.get("type")
        # print("checktype", "key:", key, "type:", syntype, "js:", js)
        if syntype == "string":
            if not isinstance(js, str):
                raise (ValueError("Das Feld " + key + " hat den Typ " + str(type(js)) + " anstatt string "))
        elif syntype == "int":
            if not isinstance(js, int):
                raise (ValueError(
                    "Das Feld " + key + " hat den Typ " + str(type(js)) + " anstatt int (d.h. eine ganze Zahl"))
        elif syntype == "bool":
            if not isinstance(js, bool):
                raise (ValueError(
                    "Das Feld " + key + " hat den Typ " + str(type(js)) + " anstatt bool (d.h. true oder false)"))
        elif syntype == "float":
            if not isinstance(js, float):
                raise (ValueError(
                    "Das Feld " + key + " hat den Typ " + str(type(js)) + " anstatt float (d.h. eine Gleitkommazahl)"))
        elif syntype == "auswahl":
            auswahl = syn.get("auswahl")
            if auswahl and js not in auswahl:
                raise ValueError(js + " nicht enthalten in der Auswahl " + str(auswahl))
        elif syntype == "array":
            if not isinstance(js, list):
                raise (ValueError("Das Feld " + key + " hat den Typ " + str(
                    type(js)) + " anstatt eine Liste zu sein"))
            else:
                syn = syn.get("elem")
                if isinstance(syn, dict):
                    for v in js:
                        self.checkSyntax(v, syn)
                else:
                    for x in js:
                        self.checkSimpleType(key, x, syn)
        elif isinstance(syntype, dict):
            if isinstance(js, dict):
                self.checkSyntax(js, syntype)
            else:
                raise (ValueError(
                    "Das Feld " + key + " hat den Typ " + str(type(js)) + " anstatt zusammengesetzt zu sein"))
        elif isinstance(syntype, list):
            raise (ValueError("Das Feld " + key + " hat den Typ " + str(type(js)) + " anstatt eine Liste zu sein"))
        else:  # if isinstance(syntype, array):
            raise ValueError("!!")

    def checkSimpleType(self, key, js, syntype):
        # print("checksimpletype", "key", key, "type:", syntype, "js:", js)
        if syntype == "string":
            if not isinstance(js, str):
                raise ValueError(
                    "Der wert " + str(js) + " im Feld " + key + " hat den Typ " + str(type(js)) + " anstatt string ")
        elif syntype == "int":
            if not isinstance(js, int):
                raise ValueError(
                    "Der wert " + str(js) + " im Feld " + key + " hat den Typ " + str(
                        type(js)) + " anstatt int (d.h. eine ganze Zahl")
        elif syntype == "bool":
            if not isinstance(js, bool):
                raise ValueError(
                    "Der wert " + str(js) + " im Feld " + key + " hat den Typ " + str(
                        type(js)) + " anstatt bool (d.h. true oder false)")
        elif syntype == "float":
            if not isinstance(js, float):
                raise ValueError(
                    "Der wert " + str(js) + " im Feld " + key + " hat den Typ " + str(
                        type(js)) + " anstatt float (d.h. eine Gleitkommazahl)")
        else:
            raise ValueError("Unbekannter Typ " + syntype + "im Feld " + key)

    def getErrors(self):
        return "\n".join(self.errors)

if __name__ == "__main__":
    cfg = Config()
    print("Geparst", cfg.getNames())
    print("Errors:", cfg.getErrors())