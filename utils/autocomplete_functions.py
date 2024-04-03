import json
import traceback
import config_extra
import nextcord
import config
import db_query
from utils.checks import get_type_emoji


async def zerpmon_autocomplete(interaction: nextcord.Interaction, item: str):
    temp_mode = False
    params = []
    user_id = str(interaction.user.id)
    try:
        params = interaction.data['options'][0]['options']
    except:
        pass
    main_type = ''
    # if params[1]['name'] == 'use_on':
    #     main_type = user_owned['equipments'][params[0]['value']]['attributes'][-1]['value']
    remove_items = [i['value'] for i in params if i['name'][0].isdigit()]
    # print(interaction.data)
    try:
        temp_mode = [i for i in interaction.data['options'][0]['options'] if i['name'] == 'deck_type'][0][
                        'value'] == 'gym_tower'
    except:
        pass
    cache = config_extra.deck_item_cache

    if temp_mode:
        cache = cache['temp']
        cache[user_id] = await db_query.get_temp_user(user_id, autoc=True)
        user_owned = cache[user_id]
        zerps = [(str(k), v) for k, v in enumerate(user_owned['zerpmons'])]
    else:
        cache = cache['main']
        # if user_id not in cache:
        cache[user_id] = await db_query.get_owned(user_id, autoc=True)
        user_owned = cache[user_id]
        zerps = [(i['sr'], i) for i in user_owned['zerpmons']]
    cards = {k: v for k, v in zerps if
             item.lower() in v['name'].lower() and k not in remove_items and
             (main_type == '' or main_type in v['type'])}
    choices = {}
    if (len(cards)) == 0:
        pass
    else:
        for k, v in cards.items():
            if len(choices) == 24:
                break
            choices[f'{v["name"]} ({", ".join(v["type"])})'] = k
    choices['Empty slot'] = ''
    await interaction.response.send_autocomplete(choices)


async def equipment_autocomplete(interaction: nextcord.Interaction, item: str):
    params = interaction.data['options'][0]['options']
    temp_mode = False
    try:
        temp_mode = [i for i in params if i['name'] == 'deck_type'][0]['value'] == 'gym_tower'
    except:
        pass
    cache = config_extra.deck_item_cache
    if temp_mode:
        user_owned = await db_query.get_temp_user(str(interaction.user.id))
    else:
        user_owned = await db_query.get_owned(interaction.user.id)
        mission_zerps = user_owned['mission_deck']
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
    z_moves = [] if not slot_zerpmon else (user_owned['zerpmons'][int(slot_zerpmon)] if temp_mode else (
        await db_query.get_zerpmon(user_owned['zerpmons'][slot_zerpmon]['name'])))['moves']
    types = config.TYPE_MAPPING if not slot_zerpmon else [i['type'] for idx, i in enumerate(z_moves) if idx < 4]
    # print(slot_zerpmon, types)
    remove_items = [i['value'] for i in params if 'equipment' in i['name']]
    if user_owned is not None and 'equipments' in user_owned:
        if temp_mode:
            choices = {f'{i["name"]} ({i["type"]})': str(k) for k, i in
                       enumerate(user_owned['equipments']) if
                       item in i['name'] and str(k) not in remove_items and (i["type"] == 'Omni' or i["type"] in types)}
        else:
            choices = {f'{i["name"]} ({get_type_emoji(i["attributes"], emoji=False)})': k for k, i in
                       user_owned['equipments'].items() if item in i['name'] and k not in remove_items and
                       any((_i['value'] == 'Omni' or _i['value'] in types) for _i in i['attributes'] if
                           _i['trait_type'] == 'Type')}
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

        user_owned = await db_query.get_owned(user_id)
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
        # c, latest_listings = await db_query.get_loan_listings(page_no=1, docs_per_page=20, zerp_name=item)
        latest_listings, extra = await db_query.get_loaned(str(interaction.user.id))
        latest_listings.extend(extra)
    else:
        latest_listings, _ = await db_query.get_loaned(str(interaction.user.id))
    choices = {}
    for item in latest_listings:
        if len(choices) >= 24:
            break
        choices[item['zerpmon_name']] = item['zerpmon_name']

    await interaction.response.send_autocomplete(choices)


async def zerp_flair_autocomplete(interaction: nextcord.Interaction, item: str):
    # Determine the choices for the trainer_name option based on a condition
    user_owned = await db_query.get_owned(interaction.user.id)
    if user_owned is not None and 'z_flair' in user_owned:
        vals = [i for i in user_owned['z_flair'] if item in i]
        choices = {i: i for i in vals}
    else:
        choices = {}
    choices = dict(sorted(choices.items()))
    await interaction.response.send_autocomplete(choices)


async def deck_num_autocomplete(interaction: nextcord.Interaction, item: str):
    params = interaction.data['options'][0]['options']
    temp_mode = False
    try:
        temp_mode = [i for i in params if i['name'] == 'deck_type'][0]['value'] == 'gym_tower'
    except:
        pass
    if not temp_mode:
        choices = {"1st": '0', "2nd": '1', "3rd": '2', "4th": '3', "5th": '4', "6th": '5', "7th": '6', "8th": '7',
                   "9th": '8', "10th": '9', "11th": '10', "12th": '11', "13th": '12', "14th": '13', "15th": '14',
                   "16th": '15', "17th": '16', "18th": '17', "19th": '18', "20th": '19'}
    else:
        choices = {"1st": '0'}
    await interaction.response.send_autocomplete(choices)


async def def_deck_autocomplete(_i: nextcord.Interaction, item: str):
    params = _i.data['options'][0]['options']

    deck_type = [i for i in params if i['name'] == 'deck_type'][0]['value']

    choices = [('1st', '0'), ('2nd', '1'), ('3rd', '2'), ('4th', '3'), ('5th', '4'), ('6th', '5'), ('7th', '6'),
               ('8th', '7'), ('9th', '8'), ('10th', '9'), ('11th', '10'), ('12th', '11'), ('13th', '12'),
               ('14th', '13'), ('15th', '14'), ('16th', '15'), ('17th', '16'), ('18th', '17'), ('19th', '18'),
               ('20th', '19')]

    deck_n_key = deck_type + 's'
    deck_names = (await db_query.get_deck_names(str(_i.user.id))).get('deck_names', {}).get(deck_n_key, {})

    for idx, (k, i) in enumerate(choices):
        if i in deck_names:
            choices[idx] = (deck_names[i] + f' ({k})', i)
    await _i.response.send_autocomplete(dict(choices))


async def zerpmon_sim_autocomplete(interaction: nextcord.Interaction, item: str):
    params = interaction.data['options']
    try:
        params = interaction.data['options'][0]['options']
    except Exception as e:
        print(e)
    remove_items = [i['value'] for i in params if i['name'][-3].isdigit()]

    zerps = await db_query.get_all_z(item)
    cards = [v for v in zerps if v['name'] not in remove_items]
    choices = {}
    if (len(cards)) == 0:
        pass
    else:
        for v in cards:
            if len(choices) == 24:
                break
            choices[f'{v["name"]} ({", ".join(v["zerpmonType"])})'] = v["name"]
    choices['Empty slot'] = ''
    await interaction.response.send_autocomplete(choices)


async def equipment_sim_autocomplete(interaction: nextcord.Interaction, item: str):
    params = interaction.data['options']
    try:
        params = params[0]['options']
    except:
        pass

    # print(params)
    focused = [i['name'] for i in params if i.get('focused', False)][0].split('_')[-1]
    print(focused)

    slot_zerpmon = [i['value'] for i in params if i['name'][-3] == focused]
    slot_zerpmon = slot_zerpmon[0] if len(slot_zerpmon) > 0 else False
    types = config.TYPE_MAPPING if not slot_zerpmon else (await db_query.get_zerpmon(slot_zerpmon))['move_types']
    print(slot_zerpmon, types)
    remove_items = [i['value'] for i in params if 'equipment' in i['name']]
    eqs = await db_query.get_all_eqs(substr=item)
    print(eqs)
    if eqs:
        choices = {f'{i["name"]} ({i["type"]})': i["name"] for i in
                   eqs if i["name"] not in remove_items and
                   i["type"] == 'Omni' or i["type"] in types}
    else:
        choices = {}
    sorted_c = sorted(choices.items())
    choices = dict(sorted_c if len(sorted_c) <= 24 else sorted_c[:24])
    choices['Empty slot'] = ''
    await interaction.response.send_autocomplete(choices)
