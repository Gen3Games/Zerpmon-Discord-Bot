import json

mapping = {
    "USA": "en.json",
    "GBR": "en.json",
    "DEU": "de.json",
    "ESP": "es.json",
    "JPN": "ja.json",
    "CHN": "cn.json",
    "IND": "en.json",
    "KOR": "ko.json"
}

list_l = ['en', 'de', 'es', 'ja', 'cn', 'ko']
battle_translations = {}


def translate_message(code: str, messages: dict, bold=True) -> list[str]:
    global battle_translations
    # code = mapping.get(code, 'en.json')
    code = code if code in list_l else 'en'
    if battle_translations.get(code) is None:
        fp = f"./static/zerpmon-translations/{code}.json"
        print(fp)
        with open(fp, "r", encoding="utf-8") as file:
            translations = json.load(file)
        translations = translations.get('battle')
        kv = translations.popitem()
        if kv[-1]:
            translations[kv[0]] = kv[1]
            battle_translations[code] = translations
        else:
            return translate_message('en', messages)
    # Find the translation for the message key
    t = battle_translations[code]
    msgs = []
    for msg in messages:
        translation = t.get(msg['key'], f"No translation found for '{msg['key']}'")

        # Replace dynamic values in the translation
        for key, value in msg.get('dynamicValues', {}).items():
            fmt = ''
            if bold:
                fmt = '**'
            translation = translation.replace(f'{{{key}}}', f'{fmt}{value if value else "⚫" }{fmt}')
        msgs.append(translation)
    return msgs
