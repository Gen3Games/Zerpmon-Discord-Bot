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


def translate_message(code: str, messages: dict) -> list[str]:
    global battle_translations
    # code = mapping.get(code, 'en.json')
    code = code if code in list_l else 'en'
    if battle_translations.get(code) is None:
        fp = f"./static/zerpmon-translations/{code}.json"
        print(fp)
        with open(fp, "r", encoding="utf-8") as file:
            translations = json.load(file)
        translations = translations.get('battle')
        if translations.popitem()[-1]:
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
            translation = translation.replace(f'{{{key}}}', f'**{value if value else "⚫" }**')
        msgs.append(translation)
    return msgs
