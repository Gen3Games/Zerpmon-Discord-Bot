import json
import traceback

import nextcord
from db_query import get_owned
from utils.checks import get_type_emoji


async def zerpmon_autocomplete(interaction: nextcord.Interaction, item: str):
    user_owned = get_owned(interaction.user.id)
    params = interaction.data['options'][0]['options']
    main_type = ''
    # if params[1]['name'] == 'use_on':
    #     main_type = user_owned['equipments'][params[0]['value']]['attributes'][-1]['value']
    remove_items = [i['value'] for i in params if i['name'][0].isdigit()]
    # print(interaction.data)
    cards = {k: v for k, v in user_owned['zerpmons'].items() if
             item.lower() in v['name'].lower() and k not in remove_items and
             (main_type == '' or main_type in [i['value'] for i in v['attributes'] if i['trait_type'] == 'Type'])}
    choices = {}
    if (len(cards)) == 0:
        pass
    else:
        for k, v in cards.items():
            if len(choices) == 24:
                break
            choices[f'{v["name"]} ({get_type_emoji(v["attributes"], emoji=False)})'] = k
    choices['Empty slot'] = ''
    await interaction.response.send_autocomplete(choices)


async def equipment_autocomplete(interaction: nextcord.Interaction, item: str):
    user_owned = get_owned(interaction.user.id)
    params = interaction.data['options'][0]['options']
    remove_items = [i['value'] for i in params if i['name'][0].isdigit() or 'equipment' in i['name']]
    if user_owned is not None and 'equipments' in user_owned:
        choices = {f'{i["name"]} ({get_type_emoji(i["attributes"], emoji=False)})': k for k, i in user_owned['equipments'].items() if item in i['name'] and k not in remove_items}
    else:
        choices = {}
    sorted_c = sorted(choices.items())
    choices = dict(sorted_c if len(sorted_c) <= 24 else sorted_c[:24])
    choices['Empty slot'] = ''
    await interaction.response.send_autocomplete(choices)


async def trade_autocomplete(interaction: nextcord.Interaction, item: str):
    try:
        # print(f"{interaction.data['options'][0]['options']}")
        params = interaction.data['options'][0]['options']
        op_id = params[1]['value']
        own = [i['value'] for i in params if i['name'] == 'give' and 'focused' in i]
        user_id = str(interaction.user.id) if len(own) > 0 else op_id
        trade_t = json.loads(params[0]['value'])['key']

        user_owned = get_owned(user_id)
        if user_owned is not None and trade_t in user_owned:
            if trade_t == 'flair':
                vals = [i for i in user_owned['flair'] if item in i]
            else:
                vals = [i.replace('./static/gym/', '').replace('.png', '') for i in user_owned['bg'] if item in i]
            choices = {i: i for i in vals}
        else:
            choices = {}
        choices = dict(sorted(choices.items()))
        await interaction.response.send_autocomplete(choices)
    except:
        print(traceback.format_exc())