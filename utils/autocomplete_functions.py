import json
import traceback

import nextcord

import config
import db_query
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
    mission_zerps = user_owned['mission_deck']
    params = interaction.data['options'][0]['options']
    # print(params)
    focused = [i['name'] for i in params if i.get('focused', False)][0].split('_')[-1]
    print(focused)
    if focused.isdigit():
        # Mission Deck
        slot_zerpmon = []
        focused = f'{int(focused) - 1}'
        if focused in mission_zerps:
            slot_zerpmon.append(mission_zerps.get(focused))
    else:
        slot_zerpmon = [i['value'] for i in params if i['name'] == focused]
    slot_zerpmon = slot_zerpmon[0] if len(slot_zerpmon) > 0 else False
    z_moves = [] if not slot_zerpmon else db_query.get_zerpmon(user_owned['zerpmons'][slot_zerpmon]['name'])['moves']
    types = config.TYPE_MAPPING if not slot_zerpmon else [i['type'] for idx, i in enumerate(z_moves) if idx < 4]
    # print(slot_zerpmon, types)
    remove_items = [i['value'] for i in params if 'equipment' in i['name']]
    if user_owned is not None and 'equipments' in user_owned:
        choices = {f'{i["name"]} ({get_type_emoji(i["attributes"], emoji=False)})': k for k, i in user_owned['equipments'].items() if item in i['name'] and k not in remove_items and
                   any((_i['value'] == 'Omni' or _i['value'] in types) for _i in i['attributes'] if _i['trait_type'] == 'Type')}
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


async def loan_autocomplete(interaction: nextcord.Interaction, item: str):
    expired = False
    flag = interaction.data['options'][0]['name']
    if 'relist' in flag:
        expired = True
    if not expired:
        # c, latest_listings = db_query.get_loan_listings(page_no=1, docs_per_page=20, zerp_name=item)
        latest_listings, extra = db_query.get_loaned(str(interaction.user.id))
        latest_listings.extend(extra)
    else:
        latest_listings, _ = db_query.get_loaned(str(interaction.user.id))
    choices = {}
    for item in latest_listings:
        if len(choices) >= 24:
            break
        choices[item['zerpmon_name']] = item['zerpmon_name']

    await interaction.response.send_autocomplete(choices)