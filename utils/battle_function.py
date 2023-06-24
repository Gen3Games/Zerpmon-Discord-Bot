import asyncio
import json
import os
import random
import time
from utils.battle_effect import apply_status_effects
import nextcord
import requests
from PIL import Image

import config
import db_query
from utils import xrpl_ws, checks


class CustomEmbed(nextcord.Embed):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.set_footer(text='Zerpmon',
                        icon_url=config.ICON_URL)


with open("./TypingMultipliers.json", 'r') as file:
    file = json.load(file)
    type_mapping = dict(file)


def check_battle_happening(channel_id):
    battles_in_channel = [i for msg, i in config.battle_dict.items() if i['channel_id'] == channel_id]
    wager_battles_in_channel = [i for msg, i in config.wager_battles.items() if i['channel_id'] == channel_id]

    return battles_in_channel == [] and wager_battles_in_channel == []


def gen_image(_id, url1, url2, path1, path2, path3):
    randomImage = f'BattleBackground{random.randint(1, 68)}.png'
    # Load the background image and resize it
    bg_img = Image.open(f'./static/bgs/{randomImage}')
    bg_img = bg_img.resize((2560, 1600))  # desired size

    # Load the three images
    download_image(url1, path1)
    download_image(url2, path3)
    img1 = Image.open(path1)
    img2 = Image.open(path2)
    img3 = Image.open(path3)

    img1 = img1.resize((1200, 1200))
    img3 = img3.resize((1200, 1200))

    # Create a new RGBA image with the size of the background image
    combined_img = Image.new('RGBA', bg_img.size, (0, 0, 0, 0))

    # Paste the background image onto the new image
    combined_img.paste(bg_img, (0, 0))

    # Paste the three images onto the new image
    combined_img.paste(img1, (50, 100), mask=img1)  # adjust the coordinates as needed
    combined_img.paste(img2, (1150, 200), mask=img2)
    combined_img.paste(img3, (1350, 100), mask=img3)

    # Resize the combined image to be 50% of its original size
    new_width = int(combined_img.width * 0.5)
    new_height = int(combined_img.height * 0.5)
    smaller_img = combined_img.resize((new_width, new_height))

    # Save the final image
    smaller_img.save(f'{_id}.png', quality=50)


def battle_zerpmons(zerpmon1_name, zerpmon2_name, types, status_affects, buffed_types, p1=None, p2=None):
    z1 = db_query.get_zerpmon(zerpmon1_name)

    # Trainer buff
    buffed1 = buffed_types[0] in types[0]
    if buffed1:
        for i, move in enumerate(z1['moves']):
            if 'dmg' in move and move['dmg'] != "":
                z1['moves'][i]['dmg'] = round(1.1 * int(move['dmg']), 1)
    # print(z1['moves'])
    percentages1 = [(float(p['percent']) if p['percent'] not in ["0.00", "0", ""] else None) for p in
                    z1['moves']] if p1 is None else p1
    # print(f'Percentages1: {percentages1}')
    z2 = db_query.get_zerpmon(zerpmon2_name)

    buffed2 = buffed_types[1] in types[1]
    if buffed2:
        for i, move in enumerate(z2['moves']):
            if 'dmg' in move and move['dmg'] != "":
                z2['moves'][i]['dmg'] = round(1.1 * int(move['dmg']), 1)
    percentages2 = [(float(p['percent']) if p['percent'] not in ["0.00", "0", ""] else None) for p in
                    z2['moves']] if p2 is None else p2
    # print(f'Percentages2: {percentages2}')

    percentages1, percentages2, m1, m2 = \
        apply_status_effects(percentages1, percentages2, status_affects if status_affects is not None else [[], []])

    # Select the random move based on Percentage weight

    indexes = list(range(len(percentages1)))

    chosen_index1 = random.choices(indexes, weights=[(0 if i is None else i) for i in percentages1])[0]
    move1 = z1['moves'][chosen_index1]

    # print(move1)

    chosen_index2 = random.choices(indexes, weights=[(0 if i is None else i) for i in percentages2])[0]
    move2 = z2['moves'][chosen_index2]
    # print(move2)

    winner = {
        'move1': {'name': move1['name'], 'color': move1['color'], 'dmg': "" if 'dmg' not in move1 else move1['dmg'],
                  'stars': "" if 'stars' not in move1 else len(move1['stars']),
                  'percent': int(percentages1[chosen_index1]), 'msg': m1,
                  'type': '' if 'type' not in move1 else move1['type'],
                  'mul': ''},
        'move2': {'name': move2['name'], 'color': move2['color'], 'dmg': "" if 'dmg' not in move2 else move2['dmg'],
                  'stars': "" if 'stars' not in move2 else len(move2['stars']),
                  'percent': int(percentages2[chosen_index2]), 'msg': m2,
                  'type': '' if 'type' not in move2 else move2['type'],
                  'mul': ''},
        'winner': ""

    }

    if 'dmg' in move1:
        d1m = 1
        # print(types[1], types[0])

        _t1 = move1['type'].lower().replace(" ", "")
        for _t2 in types[1]:
            _t2 = _t2.lower().replace(" ", "")
            d1m = d1m * type_mapping[_t1][_t2]
        # print(d1m)

        move1['dmg'] = round(d1m * int(move1['dmg']))
        winner['move1']['dmg'] = round(move1['dmg'])
        winner['move1']['mul'] = "x½" if d1m == 0.5 else f'x{d1m}'
        r_int = random.randint(1, 20)
        if r_int == 1:
            move1['dmg'] = round(2 * int(move1['dmg']))
            winner['move1']['dmg'] = round(move1['dmg'])
            winner['move1']['mul'] += " 🎯"

    if 'dmg' in move2:
        d2m = 1

        _t1 = move2['type'].lower().replace(" ", "")
        for _t2 in types[0]:
            _t2 = _t2.lower().replace(" ", "")
            d2m = d2m * type_mapping[_t1][_t2]
        # print(d2m)
        move2['dmg'] = round(d2m * int(move2['dmg']))
        winner['move2']['dmg'] = round(move2['dmg'])
        winner['move2']['mul'] = "x½" if d2m == 0.5 else f'x{d2m}'
        r_int = random.randint(1, 20)
        if r_int == 1:
            move2['dmg'] = round(2 * int(move2['dmg']))
            winner['move2']['dmg'] = round(move2['dmg'])
            winner['move2']['mul'] += " 🎯"

    # Check Color of both moves

    match (move1['color'], move2['color']):
        case ("white", "white") | ("white", "gold") | ("gold", "white") | ("gold", "gold"):

            d1 = float(move1['dmg'])
            d2 = float(move2['dmg'])

            if d1 > d2:
                winner['winner'] = '1'

            elif d1 == d2:
                winner['winner'] = ""
            else:
                winner['winner'] = '2'

        case ("white", "purple") | ("miss", "purple"):
            m2 = db_query.get_move(move2['name'])
            percentages1, percentages2, _m1, _m2 = apply_status_effects(percentages1, percentages2, [[], [m2['notes']]])

            winner['winner'] = '2'
            winner['status_effect'] = m2['notes']
            winner['move2']['msg'] = _m2

        case ("purple", "white") | ("purple", "miss"):
            m1 = db_query.get_move(move1['name'])
            percentages1, percentages2, _m1, _m2 = apply_status_effects(percentages1, percentages2, [[m1['notes']], []])

            winner['winner'] = '1'
            winner['status_effect'] = m1['notes']
            winner['move1']['msg'] = _m1

        case ("blue", "white") | ("blue", "gold") | ("blue", "purple") | ("blue", "miss") | ("white", "blue") | ("gold",
                                                                                                                 "blue") | (
                 "purple", "blue") | ("miss", "blue") | ("blue", "blue"):

            winner['winner'] = ""

        case ("white", "miss") | ("gold", "miss"):
            if move1['dmg'] == 0:
                winner['winner'] = ""
            else:
                winner['winner'] = '1'

        case ("miss", "white") | ("miss", "gold"):
            if move2['dmg'] == 0:
                winner['winner'] = ""
            else:
                winner['winner'] = '2'

        case ("gold", "purple"):
            if move1['dmg'] == 0:
                winner['winner'] = ""
            else:
                winner['winner'] = '1'

        case ("purple", "gold"):
            if move2['dmg'] == 0:
                winner['winner'] = ""
            else:
                winner['winner'] = '2'

        case ("purple", "purple"):
            s1 = len(move1['stars'])
            s2 = len(move2['stars'])
            if s1 > s2:
                m1 = db_query.get_move(move1['name'])
                percentages1, percentages2, _m1, _m2 = apply_status_effects(percentages1, percentages2,
                                                                            [[m1['notes']], []])

                winner['winner'] = '1'
                winner['status_effect'] = m1['notes']
                winner['move1']['msg'] = _m1

            elif s1 == s2:
                winner["winner"] = ""  # DRAW
            else:
                m2 = db_query.get_move(move2['name'])
                percentages1, percentages2, _m1, _m2 = apply_status_effects(percentages1, percentages2,
                                                                            [[], [m2['notes']]])

                winner['winner'] = '2'
                winner['status_effect'] = m2['notes']
                winner['move2']['msg'] = _m2

        case ("miss", "miss"):
            winner['winner'] = ""

        case _:
            print(f"IDK what this is {move1}, {move2}")

    return winner, percentages1, percentages2


bt = battle_zerpmons("Fiepion", "Elapix", [["fire"], ["Bug", "Steel"]], [[], []], ["Dark", "Dark"])
print(json.dumps(bt, indent=2))


def download_image(url, path_to_file):
    if os.path.isfile(path_to_file):
        # print(f"{path_to_file} already exists, skipping download.")
        pass
    else:
        response = requests.get(url)
        with open(path_to_file, 'wb') as f:
            f.write(response.content)
        print(f"Downloaded {path_to_file}.")


async def proceed_battle(message: nextcord.Message, battle_instance, b_type=5):
    _data1 = db_query.get_owned(battle_instance["challenger"])
    _data2 = db_query.get_owned(battle_instance["challenged"])

    trainer_embed = CustomEmbed(title=f"Trainers Battle",
                                   description=f"({battle_instance['username1']} VS {battle_instance['username2']})", color=0xf23557)

    user1_zerpmons = _data1['zerpmons']
    tc1 = list(_data1['trainer_cards'].values())[0] if ('battle_deck' not in _data1) or ('0' in _data1['battle_deck'] and ('trainer' not in _data1['battle_deck']['0'])) else \
        _data1['trainer_cards'][_data1['battle_deck']['0']['trainer']]
    tc1i = tc1['image']
    buffed_type1 = [i for i in tc1['attributes'] if i['trait_type'] == 'Affinity' or i['trait_type'] == 'Type']
    if buffed_type1 != []:
        buffed_type1 = buffed_type1[0]['value']

    user2_zerpmons = _data2['zerpmons']
    tc2 = list(_data2['trainer_cards'].values())[0] if ('battle_deck' not in _data2) or ('0' in _data2['battle_deck'] and ('trainer' not in _data2['battle_deck']['0'])) else \
        _data2['trainer_cards'][_data2['battle_deck']['0']['trainer']]
    tc2i = tc2['image']
    buffed_type2 = [i for i in tc2['attributes'] if i['trait_type'] == 'Affinity' or i['trait_type'] == 'Type']
    if buffed_type2 != []:
        buffed_type2 = buffed_type2[0]['value']

    path1 = f"./static/images/{tc1['name']}.png"
    path2 = f"./static/images/vs.png"
    path3 = f"./static/images/{tc2['name']}.png"

    url1 = tc1i if "https:/" in tc1i else 'https://cloudflare-ipfs.com/ipfs/' + tc1i.replace("ipfs://", "")
    trainer_embed.add_field(
        name=f"{tc1['name']} ({', '.join([i['value'] for i in tc1['attributes'] if i['trait_type'] == 'Affinity' or i['trait_type'] == 'Type'])})",
        value="\u200B", inline=True)

    trainer_embed.add_field(name=f"🆚", value="\u200B", inline=True)

    url2 = tc2i if "https:/" in tc2i else 'https://cloudflare-ipfs.com/ipfs/' + tc2i.replace("ipfs://", "")
    trainer_embed.add_field(
        name=f"{tc2['name']} ({', '.join([i['value'] for i in tc2['attributes'] if i['trait_type'] == 'Affinity'  or i['trait_type'] == 'Type'])})",
        value="\u200B", inline=True)

    gen_image(str(message.id) + '0', url1, url2, path1, path2, path3)

    file2 = nextcord.File(f"{message.id}0.png", filename="image0.png")
    trainer_embed.set_image(url=f'attachment://image0.png')

    low_z = max(len(user1_zerpmons), len(user2_zerpmons))
    if b_type <= low_z:
        low_z = b_type

    # Sanity check
    if 'battle_deck' in _data1 and (len(_data1['battle_deck']) == 0 or ('0' in _data1['battle_deck'] and len(_data1['battle_deck']['0']) == 0)):
        await message.reply(content=f"**{_data1['username']}** please check your battle deck, it's empty.")
    elif 'battle_deck' in _data2 and (len(_data2['battle_deck']) == 0 or ('0' in _data2['battle_deck'] and len(_data2['battle_deck']['0']) == 0)):
        await message.reply(content=f"**{_data2['username']}** please check your battle deck, it's empty.")
    # Proceed

    print("Start")
    try:
        del _data1['battle_deck']['0']['trainer']
    except:
        pass
    try:
        del _data2['battle_deck']['0']['trainer']
    except:
        pass
    if 'battle_deck' not in _data1 or (len(_data1['battle_deck']) == 0 or ('0' in _data1['battle_deck'] and len(_data1['battle_deck']['0']) == 0)):
        user1_zerpmons = list(user1_zerpmons.values())[:low_z if len(user1_zerpmons) > low_z else len(user1_zerpmons)]
    else:
        user1_z = []
        i = 0
        while len(user1_z) != len(_data1['battle_deck']['0']):
            try:
                user1_z.append(user1_zerpmons[_data1['battle_deck']['0'][str(i)]])
            except:
                pass
            i += 1
        user1_z.reverse()
        user1_zerpmons = user1_z if len(user1_z) <= low_z else user1_z[-low_z:]
    if 'battle_deck' not in _data2 or (len(_data2['battle_deck']) == 0 or ('0' in _data2['battle_deck'] and len(_data2['battle_deck']['0']) == 0)):
        user2_zerpmons = list(user2_zerpmons.values())[:low_z if len(user2_zerpmons) > low_z else len(user2_zerpmons)]
    else:
        user2_z = []
        i = 0
        while len(user2_z) != len(_data2['battle_deck']['0']):
            try:
                user2_z.append(user2_zerpmons[_data2['battle_deck']['0'][str(i)]])
            except:
                pass
            i += 1
        user2_z.reverse()
        user2_zerpmons = user2_z if len(user2_z) <= low_z else user2_z[-low_z:]

    # print(user1_zerpmons[-1], '\n', user2_zerpmons[-1], '\n', user1_zerpmons, '\n', user2_zerpmons, )

    msg_hook = message

    status_stack = [[], []]
    p1 = None
    p2 = None
    while len(user1_zerpmons) != 0 and len(user2_zerpmons) != 0:
        z1 = user1_zerpmons[-1]
        z1_moves = db_query.get_zerpmon(z1['name'])['moves']
        zimg1 = z1['image']
        z1_type = [i['value'] for i in z1['attributes'] if i['trait_type'] == 'Type']

        z2 = user2_zerpmons[-1]
        z2_moves = db_query.get_zerpmon(z2['name'])['moves']
        zimg2 = z2['image']
        z2_type = [i['value'] for i in z2['attributes'] if i['trait_type'] == 'Type']

        main_embed = CustomEmbed(title="Zerpmon rolling attacks...", color=0x35bcbf)

        path1 = f"./static/images/{z1['name']}.png"
        path2 = f"./static/images/vs.png"
        path3 = f"./static/images/{z2['name']}.png"

        url1 = zimg1 if "https:/" in zimg1 else 'https://cloudflare-ipfs.com/ipfs/' + zimg1.replace("ipfs://", "")
        main_embed.add_field(name=f"{z1['name']} ({', '.join(z1_type)})",
                             value=f"{config.TYPE_MAPPING[buffed_type1]} Trainer buff" if buffed_type1 in z1_type else "\u200B", inline=False)

        for i, move in enumerate(z1_moves):
            if move['name'] == "":
                continue
            notes = f"{db_query.get_move(move['name'])['notes']}" if move['color'] == 'purple' else ''

            main_embed.add_field(
                name=f"**{config.COLOR_MAPPING[move['color']]} Move:**",
                value=f"> **{move['name']}** \n" + \
                      (f"> Status Affect: `{notes}`\n" if notes != '' else "") + \
                      (f"> DMG: {move['dmg']}\n" if 'dmg' in move else "") + \
                      (f"> Stars: {len(move['stars']) * '★'}\n" if 'stars' in move else "") + \
                      (f"> Type: {config.TYPE_MAPPING[move['type'].replace(' ', '')]}\n" if 'type' in move else "") + \
                      f"> Percentage: {move['percent'] if p1 is None else p1[i]}%\n",
                inline=True)
        main_embed.add_field(name="\u200B", value="\u200B", inline=False)
        main_embed.add_field(name=f"🆚", value="\u200B", inline=False)
        main_embed.add_field(name="\u200B", value="\u200B", inline=False)

        url2 = zimg2 if "https:/" in zimg2 else 'https://cloudflare-ipfs.com/ipfs/' + zimg2.replace("ipfs://", "")
        main_embed.add_field(name=f"{z2['name']} ({', '.join(z2_type)})",
                             value=f"{config.TYPE_MAPPING[buffed_type2]} Trainer buff" if buffed_type2 in z2_type else "\u200B", inline=False)

        for i, move in enumerate(z2_moves):
            if move['name'] == "":
                continue
            notes = f"{db_query.get_move(move['name'])['notes']}" if move['color'] == 'purple' else ''
            main_embed.add_field(
                name=f"**{config.COLOR_MAPPING[move['color']]} Move:**",
                value=f"> **{move['name']}** \n" + \
                      (f"> Status Affect: `{notes}`\n" if notes != '' else "") + \
                      (f"> DMG: {move['dmg']}\n" if 'dmg' in move else "") + \
                      (f"> Stars: {len(move['stars']) * '★'}\n" if 'stars' in move else "") + \
                      (f"> Type: {config.TYPE_MAPPING[move['type'].replace(' ', '')]}\n" if 'type' in move else "") + \
                      f"> Percentage: {move['percent'] if p2 is None else p2[i]}%\n",
                inline=True)

        gen_image(message.id, url1, url2, path1, path2, path3)

        file = nextcord.File(f"{message.id}.png", filename="image.png")
        main_embed.set_image(url=f'attachment://image.png')

        if message.id == msg_hook.id:
            msg_hook = await msg_hook.reply(content="\u200B", embeds=[trainer_embed, main_embed], files=[file2, file])
        else:
            msg_hook = await msg_hook.reply(content="\u200B", embed=main_embed, file=file)

        eliminate = ""
        move_counter = 0
        while eliminate == "":
            await asyncio.sleep(3)
            # If battle lasts long then end it
            if move_counter == 20:
                r_int = random.randint(1, 2)
                rand_loser = z2['name'] if r_int == 2 else z1['name']
                await msg_hook.channel.send(
                    content=f"Out of nowhere, a giant **meteor** lands right on top of 💀 {rand_loser} 💀!")
                eliminate = (r_int, rand_loser)
                if r_int == 2:
                    p2 = None
                    status_stack[0] = [i for i in status_stack[0] if 'opposing' not in i]
                    status_stack[1] = [i for i in status_stack[1] if 'opposing' in i]
                    db_query.save_zerpmon_winrate(z1['name'], z2['name'])
                elif r_int == 1:
                    p1 = None
                    status_stack[1] = [i for i in status_stack[1] if 'opposing' not in i]
                    status_stack[0] = [i for i in status_stack[0] if 'opposing' in i]
                    db_query.save_zerpmon_winrate(z2['name'], z1['name'])

            result, p1, p2 = battle_zerpmons(z1['name'], z2['name'], [z1_type, z2_type], status_stack,
                                             [buffed_type1, buffed_type2], p1, p2)
            t_info1 = config.TYPE_MAPPING[result['move1']['type'].replace(" ", '')] + ' ' + result['move1']['mul']
            t_info2 = config.TYPE_MAPPING[result['move2']['type'].replace(" ", '')] + ' ' + result['move2']['mul']
            t_info1 = f'({t_info1})' if t_info1 not in ["", " "] else t_info1
            t_info2 = f'({t_info2})' if t_info2 not in ["", " "] else t_info2

            dmg1_str = f"{result['move1']['name']} {result['move1']['stars'] * '★'} (__{result['move1']['percent']}%__)" if \
                result['move1']['stars'] != '' \
                else f"{result['move1']['name']}{'ed' if result['move1']['color'] == 'miss' else f' {t_info1} ' + str(result['move1']['dmg'])} (__{result['move1']['percent']}%__)"

            dmg2_str = f"{result['move2']['name']} {result['move2']['stars'] * '★'} (__{result['move2']['percent']}%__)" if \
                result['move2']['stars'] != '' \
                else f"{result['move2']['name']}{'ed' if result['move2']['color'] == 'miss' else f' {t_info2} ' + str(result['move2']['dmg'])} (__{result['move2']['percent']}%__)"

            atk_msg = f"**{z1['name']}**\t({', '.join([config.TYPE_MAPPING[i] for i in z1_type])})\t{' used' if result['move1']['color'] != 'miss' else ''} " \
                      f"{config.COLOR_MAPPING[result['move1']['color']]}  {dmg1_str}\n" \
                      f"**{z2['name']}**\t({', '.join([config.TYPE_MAPPING[i] for i in z2_type])})\t{' used' if result['move2']['color'] != 'miss' else ''} " \
                      f"{config.COLOR_MAPPING[result['move2']['color']]}  {dmg2_str}\n" \
                      "Calculating Battle results..."

            await msg_hook.reply(content=atk_msg)

            print(result)

            # purple attacks
            if 'status_effect' in result:
                if result['winner'] == '1':

                    # status_stack[0].append(result['status_effect'])
                    new_m = result['move1']['msg'][:-1]
                    i = int(result['move1']['msg'][-1])

                    new_m = new_m.replace(config.COLOR_MAPPING[z1_moves[i]['color']], '').replace(
                        config.COLOR_MAPPING[z2_moves[i]['color']], '')
                    new_m = new_m.replace("me", ' ' + z1['name'] + '\'s ' + z1_moves[i]['name'] + '  ').replace(
                        "op", ' ' + z2['name'] + '\'s ' + z2_moves[i]['name'] + '  ')
                    new_m += f" ({str(z1_moves[i]['dmg']) + 'dmg, ' if 'dmg' in z1_moves[i] and z1_moves[i]['dmg'] != '' else ''}{(str(int(float(p2[i]))) if p2[i] is not None else 0) if 'opposing' in result['status_effect'] else (str(int(float(p1[i]))) if p1[i] is not None else 0)}%)"
                    await msg_hook.channel.send(
                        content=new_m)
                    move_counter += 1
                    continue
                else:
                    # status_stack[1].append(result['status_effect'])

                    new_m = result['move2']['msg'][:-1]
                    i = int(result['move2']['msg'][-1])

                    new_m = new_m.replace(config.COLOR_MAPPING[z1_moves[i]['color']], '').replace(
                        config.COLOR_MAPPING[z2_moves[i]['color']], '')
                    new_m = new_m.replace("me", ' ' + z2['name'] + '\'s ' + z2_moves[i]['name'] + '  ').replace(
                        "op", ' ' + z1['name'] + '\'s ' + z1_moves[i]['name'] + '  ')
                    new_m += f" ({str(z2_moves[i]['dmg']) + 'dmg, ' if 'dmg' in z2_moves[i] and z2_moves[i]['dmg'] != '' else ''}{(str(int(float(p1[i]))) if p1[i] is not None else 0) if 'opposing' in result['status_effect'] else (str(int(float(p2[i]))) if p2[i] is not None else 0)}%)"

                    await msg_hook.channel.send(
                        content=new_m)
                    move_counter += 1
                    continue

            # DRAW
            if result['winner'] == "":
                await msg_hook.channel.send(content=f"**DRAW**")
                move_counter += 1
                continue

            if result['winner'] == '1':
                await msg_hook.channel.send(content=f"{z1['name']} **knocked out** 💀 {z2['name']} 💀!" if '🎯' not in result['move1']['mul'] else f"**{z2['name']}**{random.sample(config.CRIT_STATEMENTS, 1)[0]}")
                eliminate = (2, z2['name'])
                p2 = None
                status_stack[0] = [i for i in status_stack[0] if 'opposing' not in i]
                status_stack[1] = [i for i in status_stack[1] if 'opposing' in i]
                db_query.save_zerpmon_winrate(z1['name'], z2['name'])
                move_counter += 1

            elif result['winner'] == '2':
                await msg_hook.channel.send(content=f"{z2['name']} **knocked out** 💀 {z1['name']} 💀!" if '🎯' not in result['move2']['mul'] else f"**{z1['name']}**{random.sample(config.CRIT_STATEMENTS, 1)[0]}")
                eliminate = (1, z1['name'])
                p1 = None
                status_stack[1] = [i for i in status_stack[1] if 'opposing' not in i]
                status_stack[0] = [i for i in status_stack[0] if 'opposing' in i]
                db_query.save_zerpmon_winrate(z2['name'], z1['name'])
                move_counter += 1

        if eliminate[0] == 1:
            user1_zerpmons = [i for i in user1_zerpmons if i['name'] != eliminate[1]]
            p1 = None
        elif eliminate[0] == 2:
            user2_zerpmons = [i for i in user2_zerpmons if i['name'] != eliminate[1]]
            p2 = None
        file.close()
        for i in range(3):
            try:
                os.remove(f"{message.id}.png")
                break
            except Exception as e:
                print(f"Delete failed retrying {e}")

    file2.close()
    for i in range(3):
        try:
            os.remove(f"{message.id}0.png")
            break
        except Exception as e:
            print(f"Delete failed retrying {e}")

    if len(user1_zerpmons) == 0:
        await msg_hook.channel.send(
            f"**WINNER**   👑**{battle_instance['username2']}**👑")
        db_query.update_pvp_user_wr(_data1['discord_id'], 0)
        db_query.update_pvp_user_wr(_data2['discord_id'], 1)
        return 2
    elif len(user2_zerpmons) == 0:
        await msg_hook.channel.send(
            f"**WINNER**   👑**{battle_instance['username1']}**👑")
        db_query.update_pvp_user_wr(_data1['discord_id'], 1)
        db_query.update_pvp_user_wr(_data2['discord_id'], 0)
        return 1


async def proceed_mission(interaction: nextcord.Interaction, user_id, active_zerpmon, old_num):
    serial, z1 = active_zerpmon
    z1_moves = db_query.get_zerpmon(z1['name'])['moves']
    zimg1 = z1['image']
    _data1 = db_query.get_owned(user_id)
    z1_type = [i['value'] for i in z1['attributes'] if i['trait_type'] == 'Type']
    buffed_type1 = []
    if len(_data1['trainer_cards']) > 0:
        tc1 = list(_data1['trainer_cards'].values())[0] if ('mission_trainer' not in _data1) or (_data1['mission_trainer'] == "") else \
        _data1['trainer_cards'][_data1['mission_trainer']]
        buffed_type1 = [i for i in tc1['attributes'] if i['trait_type'] == 'Affinity' or i['trait_type'] == 'Type']
        if buffed_type1 != []:
            buffed_type1 = buffed_type1[0]['value']

    z2 = db_query.get_rand_zerpmon()
    z2_moves = z2['moves']
    zimg2 = z2['image']
    z2_type = [i['value'] for i in z2['attributes'] if i['trait_type'] == 'Type']

    main_embed = CustomEmbed(title="Zerpmon rolling attacks...", color=0x8971d0)

    path1 = f"./static/images/{z1['name']}.png"
    path2 = f"./static/images/vs.png"
    path3 = f"./static/images/{z2['name']}.png"

    url1 = zimg1 if "https:/" in zimg1 else 'https://cloudflare-ipfs.com/ipfs/' + zimg1.replace("ipfs://", "")
    main_embed.add_field(name=f"{z1['name']} ({', '.join(z1_type)})",
                         value=f"{config.TYPE_MAPPING[buffed_type1]} Trainer buff" if buffed_type1 in z1_type else "\u200B", inline=False)

    for i, move in enumerate(z1_moves):
        if move['name'] == "":
            continue
        notes = f"{db_query.get_move(move['name'])['notes']}" if move['color'] == 'purple' else ''

        main_embed.add_field(
            name=f"**{config.COLOR_MAPPING[move['color']]} Move:**",
            value=f"> **{move['name']}** \n" + \
                  (f"> Status Affect: `{notes}`\n" if notes != '' else "") + \
                  (f"> DMG: {move['dmg']}\n" if 'dmg' in move else "") + \
                  (f"> Stars: {len(move['stars']) * '★'}\n" if 'stars' in move else "") + \
                  (f"> Type: {config.TYPE_MAPPING[move['type'].replace(' ', '')]}\n" if 'type' in move else "") + \
                  f"> Percentage: {move['percent']}%\n",
            inline=True)
    main_embed.add_field(name="\u200B", value="\u200B", inline=False)
    main_embed.add_field(name=f"🆚", value="\u200B", inline=False)
    main_embed.add_field(name="\u200B", value="\u200B", inline=False)

    url2 = zimg2 if "https:/" in zimg2 else 'https://cloudflare-ipfs.com/ipfs/' + zimg2.replace("ipfs://", "")
    main_embed.add_field(name=f"{z2['name']} ({', '.join(z2_type)})",
                         value="\u200B", inline=False)

    for i, move in enumerate(z2_moves):
        if move['name'] == "":
            continue
        notes = f"{db_query.get_move(move['name'])['notes']}" if move['color'] == 'purple' else ''

        main_embed.add_field(
            name=f"**{config.COLOR_MAPPING[move['color']]} Move:**",
            value=f"> **{move['name']}** \n" + \
                  (f"> Status Affect: `{notes}`\n" if notes != '' else "") + \
                  (f"> DMG: {move['dmg']}\n" if 'dmg' in move else "") + \
                  (f"> Stars: {len(move['stars']) * '★'}\n" if 'stars' in move else "") + \
                  (f"> Type: {config.TYPE_MAPPING[move['type'].replace(' ', '')]}\n" if 'type' in move else "") + \
                  f"> Percentage: {move['percent']}%\n",
            inline=True)

    gen_image(interaction.id, url1, url2, path1, path2, path3)

    file = nextcord.File(f"{interaction.id}.png", filename="image.png")
    main_embed.set_image(url=f'attachment://image.png')

    await interaction.send(content="\u200B", embed=main_embed, file=file, ephemeral=True)

    eliminate = ""
    status_stack = [[], []]
    p1 = None
    p2 = None
    move_counter = 0
    lost = 0
    while eliminate == "":
        await asyncio.sleep(3)
        result, p1, p2 = battle_zerpmons(z1['name'], z2['name'], [z1_type, z2_type], status_stack, [buffed_type1, []],
                                         p1, p2)
        t_info1 = config.TYPE_MAPPING[result['move1']['type'].replace(" ", '')] + ' ' + result['move1']['mul']
        t_info2 = config.TYPE_MAPPING[result['move2']['type'].replace(" ", '')] + ' ' + result['move2']['mul']
        t_info1 = f'({t_info1})' if t_info1 not in ["", " "] else t_info1
        t_info2 = f'({t_info2})' if t_info2 not in ["", " "] else t_info2

        dmg1_str = f"{result['move1']['name']} {result['move1']['stars'] * '★'} (__{result['move1']['percent']}%__)" if \
            result['move1']['stars'] != '' \
            else f"{result['move1']['name']}{'ed' if result['move1']['color'] == 'miss' else f' {t_info1} ' + str(result['move1']['dmg'])} (__{result['move1']['percent']}%__)"

        dmg2_str = f"{result['move2']['name']} {result['move2']['stars'] * '★'} (__{result['move2']['percent']}%__)" if \
            result['move2']['stars'] != '' \
            else f"{result['move2']['name']}{'ed' if result['move2']['color'] == 'miss' else f' {t_info2} ' + str(result['move2']['dmg'])} (__{result['move2']['percent']}%__)"

        atk_msg = f"**{z1['name']}**\t({', '.join([config.TYPE_MAPPING[i] for i in z1_type])})\t{' used' if result['move1']['color'] != 'miss' else ''} " \
                  f"{config.COLOR_MAPPING[result['move1']['color']]}  {dmg1_str}\n" \
                  f"**{z2['name']}**\t({', '.join([config.TYPE_MAPPING[i] for i in z2_type])})\t{' used' if result['move2']['color'] != 'miss' else ''} " \
                  f"{config.COLOR_MAPPING[result['move2']['color']]}  {dmg2_str}\n" \
                  "Calculating Battle results..."

        await interaction.send(content=atk_msg, ephemeral=True)

        print(result)

        # If battle lasts long then end it
        if move_counter == 20:
            r_int = random.randint(1, 2)
            rand_loser = z2['name'] if r_int == 2 else z1['name']
            await interaction.send(
                content=f"Out of nowhere, a giant **meteor** lands right on top of 💀 {rand_loser} 💀!", ephemeral=True)
            lost = r_int

        # purple attacks
        if 'status_effect' in result and lost == 0:
            if result['winner'] == '1':

                # status_stack[0].append(result['status_effect'])
                new_m = result['move1']['msg'][:-1]
                i = int(result['move1']['msg'][-1])

                new_m = new_m.replace(config.COLOR_MAPPING[z1_moves[i]['color']], '').replace(
                    config.COLOR_MAPPING[z2_moves[i]['color']], '')
                new_m = new_m.replace("me", ' ' + z1['name'] + '\'s ' + z1_moves[i]['name'] + '  ').replace(
                    "op", ' ' + z2['name'] + '\'s ' + z2_moves[i]['name'] + '  ')
                new_m += f" ({str(z1_moves[i]['dmg']) + 'dmg, ' if 'dmg' in z1_moves[i] and z1_moves[i]['dmg'] != '' else ''}{(str(int(float(p2[i]))) if p2[i] is not None else 0) if 'opposing' in result['status_effect'] else (str(int(float(p1[i]))) if p1[i] is not None else 0)}%)"
                await interaction.send(
                    content=new_m,
                    ephemeral=True)
                move_counter += 1
                continue
            else:
                # status_stack[1].append(result['status_effect'])

                new_m = result['move2']['msg'][:-1]
                i = int(result['move2']['msg'][-1])

                new_m = new_m.replace(config.COLOR_MAPPING[z2_moves[i]['color']], '').replace(
                    config.COLOR_MAPPING[z1_moves[i]['color']], '')
                new_m = new_m.replace("me", ' ' + z2['name'] + '\'s ' + z2_moves[i]['name'] + '  ').replace(
                    "op", ' ' + z1['name'] + '\'s ' + z1_moves[i]['name'] + '  ')
                new_m += f" ({str(z2_moves[i]['dmg']) + 'dmg, ' if 'dmg' in z2_moves[i] and z2_moves[i]['dmg'] != '' else ''}{(str(int(float(p1[i]))) if p1[i] is not None else 0) if 'opposing' in result['status_effect'] else (str(int(float(p2[i]))) if p2[i] is not None else 0)}%)"

                await interaction.send(
                    content=new_m,
                    ephemeral=True)
                move_counter += 1
                continue

        # Check if status effect has stacked upto 3 then knock the Zerpmon

        # DRAW
        if result['winner'] == "" and lost == 0:
            await interaction.send(content=f"**DRAW**", ephemeral=True)
            move_counter += 1
            continue

        if (result['winner'] == '1' and lost == 0) or lost == 2:
            if lost == 0:
                await interaction.send(content=f"{z1['name']} **knocked out** {z2['name']}!"  if '🎯' not in result['move1']['mul'] else f"**{z2['name']}**{random.sample(config.CRIT_STATEMENTS, 1)[0]}", ephemeral=True)
            eliminate = (2, z2['name'])
            await interaction.send(
                f"**WINNER**   👑**{interaction.user.mention}**👑",
                ephemeral=True)
            db_query.save_zerpmon_winrate(z1['name'], z2['name'])
            db_query.update_user_wr(user_id, 1)
            # Reward user on a Win
            responses = await xrpl_ws.reward_user(user_id, z1['name'])
            embed = CustomEmbed(title=f"🏆 Mission Victory 🏆",
                                   color=0x8ef6e4)
            embed.add_field(name="XP", value=10, inline=True)
            private = True
            for res in responses:
                response, reward, qty, token_id = res
                if reward is None:
                    continue
                if reward == "XRP":
                    embed.add_field(name=f"{reward}" + ' Won', value=qty, inline=True)
                else:
                    embed.add_field(name=f"{reward}" + ' Won', value=qty, inline=True)
                if reward == "NFT":
                    embed.add_field(name=f"NFT", value=token_id, inline=True)
                    embed.description = f'🔥 🔥 Congratulations {interaction.user.mention} just caught **{token_id}**!! 🔥 🔥\n@everyone'
                    private = False

            await interaction.send(
                embed=embed,
                ephemeral=private)
            if responses[0][1] in ["XRP", "NFT"]:
                if not responses[0][0]:

                    await interaction.send(
                        f"**Failed**, something went wrong.",
                        ephemeral=True)
                else:
                    await interaction.send(
                        f"**Successfully** sent `{responses[0][2]}` {responses[0][2]}",
                        ephemeral=True)

            db_query.update_battle_count(user_id, old_num)
            move_counter += 1

        elif (result['winner'] == '2' and lost == 0) or lost == 1:
            if lost == 0:
                await interaction.send(content=f"{z2['name']} **knocked out** {z1['name']}!"  if '🎯' not in result['move1']['mul'] else f"**{z1['name']}**{random.sample(config.CRIT_STATEMENTS, 1)[0]}", ephemeral=True)
            eliminate = (1, z1['name'])
            await interaction.send(
                f"Sorry you **LOST** 💀",
                ephemeral=True)

            z1['active_t'] = checks.get_next_ts()

            db_query.update_zerpmon_alive(z1, serial, user_id)
            db_query.update_user_wr(user_id, 0)
            db_query.save_zerpmon_winrate(z2['name'], z1['name'])
            db_query.update_battle_count(user_id, old_num)
            move_counter += 1

        file.close()
        for i in range(3):
            try:
                os.remove(f"{interaction.id}.png")
                break
            except Exception as e:
                print("Delete failed retrying: ", e)

    return eliminate[0]
