import asyncio
import json
import logging
import os
import random
import re
import time
import traceback
from copy import deepcopy
import config_extra
import xrpl_functions
from utils.battle_effect import apply_status_effects, update_next_atk, update_next_dmg, update_purple_stars, update_dmg, \
    get_crit_chance, apply_reroll_to_msg, set_reroll, remove_effects
import nextcord
import requests
from PIL import Image
import config
import db_query
from utils import xrpl_ws, checks

OMNI_TRAINERS = ["0008138805D83B701191193A067C4011056D3DEE2B298C55535743B50000001A",
                 "0008138805D83B701191193A067C4011056D3DEE2B298C556A3D14B60000001B",
                 "0008138805D83B701191193A067C4011056D3DEE2B298C553C7172B400000019"]


class CustomEmbed(nextcord.Embed):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.set_footer(text='Zerpmon',
                        icon_url=config.ICON_URL)


def get_val(effect):
    match = re.search(r'\b(\d+(\.\d+)?)\b', effect)
    val = int(float(match.group()))
    return val


with open("./TypingMultipliers.json", 'r') as file:
    file = json.load(file)
    type_mapping = dict(file)


def check_battle_happening(channel_id):
    battles_in_channel = [i for msg, i in config.battle_dict.items() if i['channel_id'] == channel_id]
    wager_battles_in_channel = [i for msg, i in config.wager_battles.items() if i['channel_id'] == channel_id]
    free_br_channels = [i for i in config.free_br_channels if i == channel_id]

    return battles_in_channel == [] and wager_battles_in_channel == [] and free_br_channels == []


async def send_global_message(guild, text, image, embed=None, channel_id=None):
    try:
        if channel_id is None:
            channel = nextcord.utils.get(guild.channels, name='🤖│zerpmon-caught')
        else:
            channel = nextcord.utils.get(guild.channels, id=channel_id)
        if embed:
            await channel.send(content=text, embed=embed)
        else:
            await channel.send(content=text + '\n' + image)
    except Exception as e:
        logging.error(f'ERROR: {traceback.format_exc()}')


async def send_message(msg_hook, hidden, embeds, files, content, view=None):
    # Determine where to send the message based on the 'hidden' condition
    if view is None:
        view = nextcord.ui.View()
    if hidden:
        await msg_hook.send(content=content, embeds=embeds, files=files, ephemeral=True, view=view)
    else:
        await msg_hook.send(content=content, embeds=embeds, files=files, view=view)


async def show_single_embed(i, z1, is_tower_rush, omni=False, ):
    if is_tower_rush:
        zerpmon = await db_query.get_zerpmon(z1.lower().title(), mission=True)
        zerpmon['level'] = 30
        await db_query.update_moves(zerpmon, save_z=False, effective=True)
    else:
        zerpmon = await db_query.get_zerpmon(z1.lower().title(), user_id=i.user.id)
    embed1 = await checks.get_show_zerp_embed(zerpmon, None, omni=omni)
    await i.send(content="\u200B", embeds=[embed1], files=[], ephemeral=True)


async def get_battle_view(msg, z1, z2, is_tower_rush=False):
    view = nextcord.ui.View(timeout=120)
    b1 = nextcord.ui.Button(label=f'View {z1}', style=nextcord.ButtonStyle.green, )
    b1.callback = lambda i: show_single_embed(i, z1, is_tower_rush)
    b2 = nextcord.ui.Button(label=f'View {z2}', style=nextcord.ButtonStyle.green, )
    b2.callback = lambda i: show_single_embed(i, z2, is_tower_rush)
    view.add_item(b1)
    view.add_item(b2)
    print('get_battle_view', view.children)
    return view


def set_zerp_extra_meta(zerp_list):
    for cur_zerp in zerp_list:
        cur_zerp['rounds'] = []


async def get_zerp_battle_embed(message, z1, z2, z1_obj, z2_obj, z1_type, z2_type, buffed_types, buffed_zerp1, buffed_zerp2,
                          gym_bg, p1,
                          p2, hp=None, rage=False):
    percentages1 = [(float(p['percent']) if (p['percent'] not in ["0.00", "0", ""] and p['color'] != 'blue') else None)
                    for p in
                    z1_obj['moves']] if p1 is None else p1
    percentages2 = [(float(p['percent']) if (p['percent'] not in ["0.00", "0", ""] and p['color'] != 'blue') else None)
                    for p in
                    z2_obj['moves']] if p2 is None else p2
    zimg1 = z1_obj['image']
    z1_moves = z1_obj['moves']
    zimg2 = z2_obj['image']
    z2_moves = z2_obj['moves']
    if not z1.get('applied', False):
        buffed1 = [i for i in buffed_types[0] if i in buffed_zerp1]
        if len(buffed1) > 0:
            extra_dmgs = await db_query.get_trainer_buff_dmg(z1['name'])
            for i, move in enumerate(z1_moves):
                if 'dmg' in move and move['dmg'] != "":
                    z1_moves[i]['dmg'] = round(move['dmg'] + extra_dmgs[i], 1)
    if not z2.get('applied', False):
        buffed2 = [i for i in buffed_types[1] if i in buffed_zerp2]
        if len(buffed2) > 0:
            extra_dmgs = await db_query.get_trainer_buff_dmg(z2['name'])
            for i, move in enumerate(z2_moves):
                if 'dmg' in move and move['dmg'] != "":
                    z2_moves[i]['dmg'] = round(move['dmg'] + extra_dmgs[i], 1)
    status_affects = [[], []]

    w_candy1, g_candy1, lvl_candy1 = z1_obj.get('white_candy', 0), z1_obj.get('gold_candy', 0), z1_obj.get(
        'licorice', 0)
    w_candy2, g_candy2, lvl_candy2 = z2_obj.get('white_candy', 0), z2_obj.get('gold_candy', 0), z2_obj.get(
        'licorice', 0)
    print(z1.get('buff_eq'), z2.get('buff_eq'))
    eq1_note = await db_query.get_eq_by_name(z1.get('buff_eq')) if z1.get('buff_eq') is not None else {}
    if hp and z2.get('buff_eq') is None:
        z2['buff_eq'] = 'Fairy Dust'
    eq2_note = await db_query.get_eq_by_name(z2.get('buff_eq')) if z2.get('buff_eq') is not None else {}
    extra_star1, extra_star2, dmg_f1, dmg_f2 = 0, 0, 1, 1
    eq1_lower_list = [i.lower() for i in eq1_note.get('notes', [])]
    eq2_lower_list = [i.lower() for i in eq2_note.get('notes', [])]
    if 'buff_eq2' in z2:
        eq2_note2 = await db_query.get_eq_by_name(z2.get('buff_eq2'))
        for i in eq2_note2['notes']:
            eq2_lower_list.append(i.lower())
    print(z1, z2)
    z1_blue_percent = 0 if z1_obj['moves'][6]['percent'] in ["0.00", "0", ""] else float(z1_obj['moves'][6]['percent'])
    z2_blue_percent = 0 if z2_obj['moves'][6]['percent'] in ["0.00", "0", ""] else float(z2_obj['moves'][6]['percent'])
    blue_dict = {'orig_b1': z1_blue_percent, 'orig_b2': z2_blue_percent, 'new_b1': z1_blue_percent,
                 'new_b2': z2_blue_percent}

    for eq1_lower in eq1_lower_list:
        if ('opponent miss chance' in eq1_lower and z1.get('eq_applied_m', '') != z2['name']) or (
                'eq_applied_m' not in z1 and 'miss chance' in eq1_lower):
            # if 'own miss chance' in eq1_lower:
            #     match = re.search(r'\b(\d+(\.\d+)?)\b', eq1_lower)
            #     buffer_m = (int(float(match.group())) if match is not None else 0)
            #     percentages1[-1] -= buffer_m
            # z1['buffer_miss'] = (int(float(match.group())) if match is not None else 0) - float(z1_moves[-1]['percent'])
            # if z1['buffer_miss'] < 0:
            #     z1['buffer_miss'] = 0
            if not rage or 'oppo' not in eq1_lower:
                z1['eq_applied_m'] = z2['name']
                status_affects[0].append(eq1_lower)
        elif ('opponent blue chance' in eq1_lower and z1.get('op_eq_applied', '') != z2['name']) or \
                (z2.get('eq_applied', '') != z1['name'] not in z1 and 'own blue chance' in eq1_lower):
            match = re.search(r'\b(\d+(\.\d+)?)\b', eq1_lower)
            percent_c = float(match.group()) if match is not None else 0
            if 'oppo' in eq1_lower:
                blue_dict['new_b2'] -= percent_c
                z1['op_eq_applied'] = z2['name']
            else:
                # z1['eq_applied'] = z2['name']
                blue_dict['new_b1'] += percent_c
                z1['eq_applied'] = z1['name']
        else:
            match = re.search(r'\b(\d+(\.\d+)?)\b', eq1_lower)
            eq_val = int(float(match.group())) if match is not None else 0
            if 'increase' in eq1_lower and 'star' in eq1_lower:
                extra_star1 = eq_val
            elif 'own damage' in eq1_lower:
                val = -(eq_val / 100)
                if 'increase' in eq1_lower:
                    val *= -1
                dmg_f1 += val
    for eq2_lower in eq2_lower_list:
        if ('opponent miss chance' in eq2_lower and z2.get('eq_applied_m', '') != z1['name']) or (
                'eq_applied_m' not in z2 and 'miss chance' in eq2_lower):
            # if 'own miss chance' in eq2_lower:
            #     match = re.search(r'\b(\d+(\.\d+)?)\b', eq2_lower)
            #     buffer_m = (int(float(match.group())) if match is not None else 0)
            #     percentages2[-1] -= buffer_m
            # z2['buffer_miss'] = (int(float(match.group())) if match is not None else 0) - float(z2_moves[-1]['percent'])
            # if z2['buffer_miss'] < 0:
            #     z2['buffer_miss'] = 0
            z2['eq_applied_m'] = z1['name']
            status_affects[1].append(eq2_lower)
        elif ('opponent blue chance' in eq2_lower and z2.get('op_eq_applied', '') != z1['name']) or \
                (z2.get('eq_applied', '') != z1['name'] and 'own blue chance' in eq2_lower):
            match = re.search(r'\b(\d+(\.\d+)?)\b', eq2_lower)
            percent_c = float(match.group()) if match is not None else 0
            if 'oppo' in eq2_lower:
                blue_dict['new_b1'] -= percent_c
                z2['op_eq_applied'] = z1['name']
            else:
                # z2['eq_applied'] = z1['name']
                blue_dict['new_b2'] += percent_c
                z2['eq_applied'] = z1['name']
        else:
            match = re.search(r'\b(\d+(\.\d+)?)\b', eq2_lower)
            eq_val = int(float(match.group())) if match is not None else 0
            if 'increase' in eq2_lower and 'star' in eq2_lower:
                extra_star2 = eq_val
            elif 'own damage' in eq2_lower:
                val = -(eq_val / 100)
                if 'increase' in eq2_lower:
                    val *= -1
                dmg_f2 += val
    dmg_f1 += z1_obj.get('extra_dmg_p', 0) / 100
    dmg_f2 += z2_obj.get('extra_dmg_p', 0) / 100
    print(extra_star1, extra_star2)
    p1, p2, m1, m2 = await apply_status_effects(percentages1.copy(), percentages2.copy(), status_affects)

    main_embed = CustomEmbed(title="Zerpmon rolling attacks...", color=0x35bcbf)
    path1 = f"./static/images/{z1_obj['name']}.png"
    path2 = f"./static/images/vs.png"
    path3 = f"./static/images/{z2_obj['name']}.png"
    z1_asc = z1_obj.get("ascended", False)
    z2_asc = z2_obj.get("ascended", False)

    url1 = zimg1 if "https:/" in zimg1 else 'https://cloudflare-ipfs.com/ipfs/' + zimg1.replace("ipfs://", "")
    main_embed.add_field(
        name=f"{z1_obj['name2']} ({', '.join(z1_type)})\t`{w_candy1}x🍬\t{g_candy1}x🍭`\t" + (
            f' (**Ascended** ☄️)' if z1_asc else ''),
        value=f"{config.TYPE_MAPPING[buffed_zerp1]} **Trainer buff**" if buffed_zerp1 != '' else "\u200B",
        inline=False)
    if eq1_note != {}:
        main_embed.add_field(
            name=f"{config.TYPE_MAPPING[eq1_note.get('type')]} Equipment",
            value=f"{z1.get('buff_eq')}:\n" + '\n'.join([f"`{i}`" for i in eq1_note['notes']]),
            inline=False)

    for i, move in enumerate(z1_moves):
        if move['color'] != 'blue':
            move['percent'] = round(p1[i], 2)
            if not z1_obj.get('applied', False):
                if 'dmg' in move:
                    move['dmg'] = round(move['dmg'] * dmg_f1)
                elif 'stars' in move:
                    move['stars'] = (len(move['stars']) + extra_star1)
        notes = f"{(await db_query.get_move(move['name']))['notes']}" if move['color'] == 'purple' else ''
        _p = move['percent'] if move['color'] != 'blue' else blue_dict['new_b1']
        main_embed.add_field(
            name=f"**{config.COLOR_MAPPING[move['color']]} Move:**",
            value=f"> **{move['name']}** \n" + \
                  (f"> Status Affect: `{notes}`\n" if notes != '' else "") + \
                  (f"> DMG: {move['dmg']}\n" if 'dmg' in move else "") + \
                  (f"> Stars: {move['stars'] * '★'}\n" if 'stars' in move else "") + \
                  (f"> Type: {config.TYPE_MAPPING[move['type'].replace(' ', '')]}\n" if 'type' in move else "") + \
                  f"> Percentage: {_p}%\n",
            inline=True)
    main_embed.add_field(name="\u200B", value="\u200B", inline=False)
    main_embed.add_field(name=f"🆚", value="\u200B", inline=False)
    main_embed.add_field(name="\u200B", value="\u200B", inline=False)

    url2 = zimg2 if "https:/" in zimg2 else 'https://cloudflare-ipfs.com/ipfs/' + zimg2.replace("ipfs://", "")
    main_embed.add_field(
        name=f"{z2['name2']} ({', '.join(z2_type)})\t`{w_candy2}x🍬\t{g_candy2}x🍭`\t" + (
            f' (**Ascended** ☄️)' if z2_asc else ''),
        value=f"{config.TYPE_MAPPING[buffed_zerp2]} **Trainer buff**" if buffed_zerp2 != '' else "\u200B",
        inline=False)
    if eq2_note != {}:
        main_embed.add_field(
            name=f"{config.TYPE_MAPPING[eq2_note.get('type')]} Equipment",
            value=f"{z2.get('buff_eq')}:\n" + '\n'.join([f"`{i}`" for i in eq2_note['notes']]),
            inline=False)
        if 'buff_eq2' in z2:
            main_embed.add_field(
                name=f"{config.TYPE_MAPPING[eq2_note2.get('type')]} Equipment",
                value=f"{z2.get('buff_eq2')}:\n" + '\n'.join([f"`{i}`" for i in eq2_note2['notes']]),
                inline=False)
    for i, move in enumerate(z2_moves):
        if move['color'] != 'blue':
            move['percent'] = round(p2[i], 2)
            if not z2_obj.get('applied', False):
                if 'dmg' in move:
                    move['dmg'] = round(move['dmg'] * dmg_f2)
                elif 'stars' in move:
                    move['stars'] = (len(move['stars']) + extra_star2)
        notes = f"{(await db_query.get_move(move['name']))['notes']}" if move['color'] == 'purple' else ''
        _p = move['percent'] if move['color'] != 'blue' else blue_dict['new_b2']
        main_embed.add_field(
            name=f"**{config.COLOR_MAPPING[move['color']]} Move:**",
            value=f"> **{move['name']}** \n" + \
                  (f"> Status Affect: `{notes}`\n" if notes != '' else "") + \
                  (f"> DMG: {move['dmg']}\n" if 'dmg' in move else "") + \
                  (f"> Stars: {move['stars'] * '★'}\n" if 'stars' in move else "") + \
                  (f"> Type: {config.TYPE_MAPPING[move['type'].replace(' ', '')]}\n" if 'type' in move else "") + \
                  f"> Percentage: {_p}%\n",
            inline=True)
    if hp is not None:
        main_embed.add_field(
            name=f"**HP 💚:**",
            value=f"> **{hp}**",
            inline=True)

    await gen_image(message.id, url1, url2, path1, path2, path3, gym_bg=gym_bg, eq1=z1.get('buff_eq', None),
              eq2=z2.get('buff_eq', None), zerp_ascension=[z1_asc, z2_asc] if z1_asc or z2_asc else None)

    file = nextcord.File(f"{message.id}.png", filename="image.png")
    main_embed.set_image(url=f'attachment://image.png')
    print(blue_dict)
    z1_obj['applied'] = True
    z2_obj['applied'] = True
    return main_embed, file, p1, p2, eq1_lower_list, eq2_lower_list, blue_dict


async def gen_image(_id, url1, url2, path1, path2, path3, gym_bg=False, eq1=None, eq2=None, ascend=False, zerp_ascension=None):
    if gym_bg and gym_bg is not None:
        bg_img = Image.open(gym_bg)
    elif ascend:
        bg_img = Image.open(f'./static/bgs/ascend.png')
    else:
        randomImage = f'BattleBackground{random.randint(1, 68)}.png'
        # Load the background image and resize it
        bg_img = Image.open(f'./static/bgs/{randomImage}')
    bg_img = bg_img.resize((2560, 1600))  # desired size

    # Load the three images
    await download_image(url1, path1)
    await download_image(url2, path3)

    img1 = Image.open(path1)
    if not ascend:
        img2 = Image.open(path2)
    img3 = Image.open(path3)

    img1 = img1.resize((1200, 1200))
    img3 = img3.resize((1200, 1200))

    if eq1:
        extra_img1 = Image.open(f"./static/images/_eq/{eq1}.png")
        extra_img1 = extra_img1.resize((400, 400))
        # Paste the extra images at the top right corner of img1 and img2
        img1.paste(extra_img1, (1200 - 580, 1250 - 580), mask=extra_img1)
    if eq2:
        extra_img2 = Image.open(f"./static/images/_eq/{eq2}.png")
        extra_img2 = extra_img2.resize((400, 400))
        img3.paste(extra_img2, (1200 - 580, 1250 - 580), mask=extra_img2)
    if zerp_ascension:
        extra_img1 = Image.open(f"./static/images/_ascension.png")
        if zerp_ascension[0]:
            img1.paste(extra_img1, (1200 - 420, 0), mask=extra_img1)
        if zerp_ascension[1]:
            img3.paste(extra_img1, (1200 - 420, 0), mask=extra_img1)
    # Create new images with 1/10th of the original size

    # Create a new RGBA image with the size of the background image
    combined_img = Image.new('RGBA', bg_img.size, (0, 0, 0, 0))

    # Paste the background image onto the new image
    combined_img.paste(bg_img, (0, 0))

    # Paste the three images onto the new image
    combined_img.paste(img1, (50, 100), mask=img1)  # adjust the coordinates as needed
    if not ascend:
        combined_img.paste(img2, (1150, 200), mask=img2)
    combined_img.paste(img3, (1350, 100), mask=img3)

    # Resize the combined image to be 50% of its original size
    new_width = int(combined_img.width * 0.5)
    new_height = int(combined_img.height * 0.5)
    smaller_img = combined_img.resize((new_width, new_height))

    # Save the final image
    smaller_img.save(f'{_id}.png', quality=50)


async def battle_zerpmons(zerpmon1, zerpmon2, types, status_affects, eq_lists, buff_eqs, p1=None, p2=None,
                    p1_temp=None,
                    p2_temp=None, mission=False, blue_dict=None, idx1=None, idx2=None, is_boss=False, rage=False):
    uid1, uid2 = None, None
    if type(zerpmon1) is tuple:
        uid1, zerpmon1 = zerpmon1
    if type(zerpmon2) is tuple:
        uid2, zerpmon2 = zerpmon2
    z1 = zerpmon1
    print(idx1, idx2, p1, p2, p1_temp, p2_temp)
    eq1_list = eq_lists[0]
    eq1_vals = []
    for eq1 in eq1_list:
        match = re.search(r'\b(\d+(\.\d+)?)\b', eq1)
        eq1_val = float(match.group()) if match is not None else 0
        eq1_vals.append(int(eq1_val) if 'star' in eq1 else eq1_val)

    eq2_list = eq_lists[1]
    eq2_vals = []
    for eq2 in eq2_list:
        match = re.search(r'\b(\d+(\.\d+)?)\b', eq2)
        eq2_val = float(match.group()) if match is not None else 0
        eq2_vals.append(int(eq2_val) if 'star' in eq2 else eq2_val)

    # print(z1['moves'])
    percentages1 = [(float(p['percent']) if (p['percent'] not in ["0.00", "0", ""] and p['color'] != 'blue') else None)
                    for p in
                    z1['moves']] if p1 is None else p1
    if p1_temp is None:
        p1_temp = percentages1

    # print(f'Percentages1: {percentages1}')
    z2 = zerpmon2
    percentages2 = [(float(p['percent']) if (p['percent'] not in ["0.00", "0", ""] and p['color'] != 'blue') else None)
                    for p in
                    z2['moves']] if p2 is None else p2
    if p2_temp is None:
        p2_temp = percentages2
    z1_blue_percent = max(0, blue_dict['new_b1'])
    z2_blue_percent = max(0, blue_dict['new_b2'])
    # print(f'Percentages2: {percentages2}')
    # if 'miss chance' in eq1:
    #     status_affects[0].append(eq1)
    # if 'miss chance' in eq2:
    #     status_affects[1].append(eq2)
    percentages1, percentages2, m1, m2 = \
        await apply_status_effects(percentages1, percentages2, status_affects if status_affects is not None else [[], []],
                             is_boss=is_boss)

    # Select the random move based on Percentage weight

    indexes = list(range(len(percentages1)))

    chosen_index1 = random.choices(indexes, weights=[(0 if i is None or i < 0 else i) for i in p1_temp])[
        0] if idx1 is None else idx1['idx']
    move1 = z1['moves'][chosen_index1].copy()
    p1_temp = percentages1
    # print(move1)

    chosen_index2 = random.choices(indexes, weights=[(0 if i is None or i < 0 else i) for i in p2_temp])[
        0] if idx2 is None else idx2['idx']
    move2 = z2['moves'][chosen_index2].copy()
    p2_temp = percentages2
    # print(move2)

    winner = {
        'move1': {'name': move1['name'], 'color': move1['color'], 'dmg': "" if 'dmg' not in move1 else move1['dmg'],
                  'stars': "" if 'stars' not in move1 else move1['stars'],
                  'percent': round(float(p1_temp[chosen_index1])), 'msg': m1,
                  'type': '' if 'type' not in move1 else move1['type'],
                  'mul': '', 'idx': chosen_index1},
        'move2': {'name': move2['name'], 'color': move2['color'], 'dmg': "" if 'dmg' not in move2 else move2['dmg'],
                  'stars': "" if 'stars' not in move2 else move2['stars'],
                  'percent': round(float(p2_temp[chosen_index2])), 'msg': m2,
                  'type': '' if 'type' not in move2 else move2['type'],
                  'mul': '', 'idx': chosen_index2},
        'winner': ""

    }

    # p1_temp, p2_temp, status_affects[0] = update_next_atk(percentages1, percentages2, chosen_index1, chosen_index2,
    #                                                       status_affect_solo=status_affects[0])
    # p2_temp, p1_temp, status_affects[1] = update_next_atk(p2_temp, p1_temp, chosen_index2, chosen_index1,
    #                                                       status_affect_solo=status_affects[1])

    print(p1, p2, p1_temp, p2_temp)

    if move1['color'] == 'purple':
        winner['move1']['stars'], status_affects[1] = update_purple_stars(winner['move1']['stars'], status_affects[1])
        z2_blue_percent /= 2
    if move2['color'] == 'purple':
        winner['move2']['stars'], status_affects[0] = update_purple_stars(winner['move2']['stars'], status_affects[0])
        z1_blue_percent /= 2

    # Check if blue triggering before moving further
    z1_blue_trigger = random.choices([True, False], [z1_blue_percent, 100 - z1_blue_percent])[
        0] if idx1 is None else False

    z2_blue_trigger = random.choices([True, False], [z2_blue_percent, 100 - z2_blue_percent])[
        0] if idx2 is None else False

    old_dmg1, old_dmg2 = winner['move1']['dmg'], winner['move2']['dmg']
    new_dmg1, new_dmg2, status_affects[0] = update_dmg(old_dmg1, old_dmg2, status_affects[0])
    new_dmg2, new_dmg1, status_affects[1] = update_dmg(new_dmg2, new_dmg1, status_affects[1])
    print(f'dmg: {new_dmg1}, {new_dmg2}', winner)

    condition_ko1, condition_ko2 = False, False
    decided = False
    if 'dmg' in move1:
        move1['dmg'] = new_dmg1 if type(new_dmg1) is not str else move1['dmg']
        d1m = 1.0
        # print(types[1], types[0])
        if not is_boss:
            _t1 = move1['type'].lower().replace(" ", "")
            for _t2 in types[1]:
                _t2 = _t2.lower().replace(" ", "")
                d1m = d1m * type_mapping[_t1][_t2]
        d1m = int(d1m) if float(d1m).is_integer() else d1m
        # print(d1m)
        d1m_t, status_affects[1] = update_next_dmg(status_affect_solo=status_affects[1])
        move1['dmg'] = round(d1m * int(move1['dmg']) * d1m_t)
        winner['move1']['dmg'] = round(move1['dmg'])
        winner['move1']['mul'] = "x½" if d1m == 0.5 else f'x{d1m}'
        for idx, eq2 in enumerate(eq2_list):
            if 'reduce opponent damage' in eq2:
                move1['dmg'] = round((1 - (eq2_vals[idx] / 100)) * int(move1['dmg']))
                winner['move1']['dmg'] = round(move1['dmg'])
            elif move1['color'] == 'gold' and 'enemy gold attack to do 0 damage' in eq2:
                new_dmg = random.choices([0, move1['dmg']], [eq2_vals[idx], 100 - eq2_vals[idx]])[0]
                if new_dmg == 0:
                    winner['eq2_name'] = buff_eqs[1]
                    winner['eq_name'] = buff_eqs[1]
                    winner['eq2_msg'] = f"✨**{buff_eqs[1]}**✨ ({z2['name2']})"
                    # winner['z1_blue_void'] = True
                move1['dmg'] = new_dmg
                winner['move1']['dmg'] = new_dmg
        crit = get_crit_chance(eq1_list, z1.get('extra_crit_p', 0))
        # print(f'crit_chance {z1["name"]} {crit}')
        if idx1 is not None:
            if '🎯' in idx1['mul']:
                winner['move1']['mul'] += " 🎯"
            move1['dmg'] = idx1['dmg']
            winner['move1']['dmg'] = idx1['dmg']
        elif crit:
            move1['dmg'] = round(2 * int(move1['dmg']))
            winner['move1']['dmg'] = round(move1['dmg'])
            winner['move1']['mul'] += " 🎯"

    if 'dmg' in move2:
        move2['dmg'] = new_dmg2 if type(new_dmg2) is not str else move2['dmg']
        if is_boss:
            if rage:
                move2['dmg'] += 150
            d2m = 0.75
        else:
            d2m = 1.0

            _t1 = move2['type'].lower().replace(" ", "")
            for _t2 in types[0]:
                _t2 = _t2.lower().replace(" ", "")
                d2m = d2m * type_mapping[_t1][_t2]
                d2m = int(d2m) if float(d2m).is_integer() else d2m

        d2m_t, status_affects[0] = update_next_dmg(status_affect_solo=status_affects[0])
        # print(d2m)
        move2['dmg'] = round(d2m * int(move2['dmg']) * d2m_t)
        winner['move2']['dmg'] = round(move2['dmg'])
        winner['move2']['mul'] = "x½" if d2m == 0.5 else f'x{d2m}'
        for idx, eq1 in enumerate(eq1_list):
            if 'reduce opponent damage' in eq1:
                move2['dmg'] = round((1 - (eq1_vals[idx] / 100)) * move2['dmg'])
                winner['move2']['dmg'] = round(move2['dmg'])
            elif move2['color'] == 'gold' and 'enemy gold attack to do 0 damage' in eq1:
                new_dmg = random.choices([0, move2['dmg']], [eq1_vals[idx], 100 - eq1_vals[idx]])[0]
                if new_dmg == 0:
                    winner['eq_name'] = buff_eqs[0]
                    winner['eq1_name'] = buff_eqs[1]
                    winner['eq1_msg'] = f"✨**{buff_eqs[0]}**✨ ({z1['name2']})"
                    # winner['z2_blue_void'] = True # if move2['dmg'] > move1.get('dmg', 0) else False
                move2['dmg'] = new_dmg
                winner['move2']['dmg'] = new_dmg
        crit = get_crit_chance(eq2_list, z2.get('extra_crit_p', 0))
        # print(f'crit_chance {z2["name"]} {crit}')
        if idx2 is not None:
            if '🎯' in idx2['mul']:
                winner['move2']['mul'] += " 🎯"
            move2['dmg'] = idx2['dmg']
            winner['move2']['dmg'] = idx2['dmg']
        elif crit:
            move2['dmg'] = round(2 * int(move2['dmg']))
            winner['move2']['dmg'] = round(move2['dmg'])
            winner['move2']['mul'] += " 🎯"

        if move2['dmg'] > move1.get('dmg', 0):
            if move1['color'] == 'purple' and winner['move1']['stars'] > 0:
                m1 = await db_query.get_move(move1['name'])
                note = m1['notes'].lower()
                if 'knock' in note and 'against' in note and move2['color'].lower() in note:
                    condition_ko1 = True
                    z1_blue_trigger = False

        for idx, eq2 in enumerate(eq2_list):

            # if 'own damage' in eq2:
            #     val = -(eq2_vals[idx] / 100)
            #     if 'increase' in eq2:
            #         val *= -1
            #     move2['dmg'] = round((1 + val) * move2['dmg'])
            #     winner['move2']['dmg'] = round(move2['dmg'])

            if 'pierce opponent' in eq2:
                if move2['dmg'] > move1.get('dmg', 0):
                    if ((move2['color'] == 'white' and move1['color'] == 'purple' and winner['move1']['stars'] > 0) or (
                            move2['color'] in ['white', 'gold'] and z1_blue_trigger)):

                        trigger = random.choices([True, False], [eq2_vals[idx], 100 - eq2_vals[idx]])[0]
                        m_name = move1['name'] if (
                                move2['color'] == 'white' and move1['color'] == 'purple' and winner['move1'][
                            'stars'] > 0) else z1['moves'][6]['name']
                        if trigger:
                            decided = True
                            winner['eq2_msg'] = f"✨**{buff_eqs[1]}**✨ ({z2['name2']})\n"
                            if random.randint(1, 2) == 1:
                                winner[
                                    'eq2_msg'] += f"{z2['name2']}'s **{move2['name']}** has miraculously pierced through {z1['name2']}'s {m_name}!"
                                winner['winner'] = '2'
                            else:
                                winner[
                                    'eq2_msg'] += f"{z2['name2']}'s **{move2['name']}** has successfully nullified {z1['name2']}'s {m_name}!"
                                winner['winner'] = '2'
                            winner['eq2_name'] = buff_eqs[1]
                            winner['eq_name'] = buff_eqs[1]
                            if not (move2['color'] == 'white' and move1['color'] == 'purple'):
                                winner['z1_blue_void'] = True
                            else:
                                z1_blue_trigger = False
                        else:
                            winner[
                                'eq2_msg'] = f"{z2['name2']}'s **{move2['name']}** couldn't break through {z1['name2']}'s **{m_name}**!"
                            winner['eq2_name'] = buff_eqs[1]

    if 'dmg' in move1:
        if move1['dmg'] > move2.get('dmg', 0):
            if move2['color'] == 'purple' and winner['move2']['stars'] > 0:
                m2 = await db_query.get_move(move2['name'])
                note = m2['notes'].lower()
                if 'knock' in note and 'against' in note and move1['color'].lower() in note:
                    condition_ko2 = True
                    z2_blue_trigger = False
        for idx, eq1 in enumerate(eq1_list):
            # if 'own damage' in eq1:
            #     val = -(eq1_vals[idx] / 100)
            #     if 'increase' in eq1:
            #         val *= -1
            #     move1['dmg'] = round((1 + val) * move1['dmg'])
            #     winner['move1']['dmg'] = round(move1['dmg'])

            if 'pierce opponent' in eq1:
                if move1['dmg'] > move2.get('dmg', 0):
                    if (move1['color'] == 'white' and move2['color'] == 'purple' and winner['move2']['stars'] > 0) or (
                            move1['color'] in ['white', 'gold'] and z2_blue_trigger):

                        trigger = random.choices([True, False], [eq1_vals[idx], 100 - eq1_vals[idx]])[0]
                        m_name = move2['name'] if (
                                move1['color'] == 'white' and move2['color'] == 'purple' and winner['move2'][
                            'stars'] > 0) else z2['moves'][6]['name']
                        if trigger:
                            decided = True
                            winner['eq1_msg'] = f"✨**{buff_eqs[0]}**✨ ({z1['name2']})\n"
                            if random.randint(1, 2) == 1:
                                winner['eq1_msg'] += f"{z1['name2']}'s **{move1['name']}** has miraculously pierced through {z2['name2']}'s {m_name}!"
                                winner['winner'] = '1'
                            else:
                                winner['eq1_msg'] += f"{z1['name2']}'s **{move1['name']}** has successfully nullified {z2['name2']}'s {m_name}!"
                                winner['winner'] = '1'
                            winner['eq1_name'] = buff_eqs[0]
                            winner['eq_name'] = buff_eqs[0]
                            if not (move1['color'] == 'white' and move2['color'] == 'purple'):
                                winner['z2_blue_void'] = True
                            else:
                                z2_blue_trigger = False
                        else:
                            winner[
                                'eq1_msg'] = f"{z1['name2']}'s **{move1['name']}** couldn't break through {z2['name2']}'s **{m_name}**!"
                            winner['eq1_name'] = buff_eqs[0]
    if new_dmg1 != old_dmg1:
        n_dmg = winner['move1']['dmg']
        winner[
            'dmg_str1'] = f" ({old_dmg1} x{int(n_dmg / old_dmg1)}) {n_dmg} {'❤️‍🩹' if n_dmg < old_dmg1 else '❤️‍🔥'} "
    if new_dmg2 != old_dmg2:
        n_dmg = winner['move2']['dmg']
        winner[
            'dmg_str2'] = f" ({old_dmg2} x{int(n_dmg / old_dmg2)}) {n_dmg} {'❤️‍🩹' if n_dmg < old_dmg2 else '❤️‍🔥'} "
    # Check Color of both moves
    pre_percentages1, pre_percentages2 = percentages1.copy(), percentages2.copy()

    if move1['color'] == 'miss':
        for idx, eq1 in enumerate(eq1_list):
            if 'roll again' in eq1:
                trigger = random.choices([True, False], [eq1_vals[idx], 100 - eq1_vals[idx]])[0]
                if trigger:
                    decided = True
                    winner['reset_roll1'] = True
                    winner['eq1_msg'] = f"✨**{buff_eqs[0]}**✨ ({z1['name2']})"
                    winner['eq1_name'] = buff_eqs[0]
    if move2['color'] == 'miss':
        for idx, eq2 in enumerate(eq2_list):
            if 'roll again' in eq2:
                trigger = random.choices([True, False], [eq2_vals[idx], 100 - eq2_vals[idx]])[0]
                if trigger:
                    decided = True
                    winner['reset_roll2'] = True
                    winner['eq2_msg'] = f"✨**{buff_eqs[1]}**✨ ({z2['name2']})"
                    winner['eq2_name'] = buff_eqs[1]

    if not decided:
        match (move1['color'], move2['color']):
            case ("white", "white") | ("white", "gold") | ("gold", "white") | ("gold", "gold"):

                d1 = float(winner['move1']['dmg'])
                d2 = float(winner['move2']['dmg'])

                if d1 > d2:
                    winner['winner'] = '1'

                elif d1 == d2:
                    winner['winner'] = ""
                else:
                    winner['winner'] = '2'

            case ("white", "purple") | ("miss", "purple"):
                if winner['move2']['stars'] > 0:
                    m2 = await db_query.get_move(move2['name'])
                    note = m2['notes'].lower()
                    percentages1, percentages2, _m1, _m2 = await apply_status_effects(percentages1, percentages2,
                                                                                [[], [note]])
                    p1_temp, p2_temp = percentages1, percentages2
                    winner['winner'] = '2'
                    winner['status_effect'] = note
                    # winner['status_effect'] = note if not rage else 'knock out'
                    winner['move2']['msg'] = _m2
                elif move1['color'] == 'white' and winner['move1']['dmg'] > 0:
                    winner['winner'] = '1'
                    winner['status_effect'] = '@sc'
                    winner['move1'][
                        'msg'] = f'''{z2['name2']}'s {move2['name']} was ineffective because it has 0 stars! {z1['name2']}'s {move1['name']} breaks through with ease!'''
                else:
                    winner['winner'] = ""
                    winner['status_effect'] = '@sc'
                    winner['move1'][
                        'msg'] = f'''{z2['name2']}'s {move2['name']} was ineffective because it has 0 stars!'''

            case ("purple", "white") | ("purple", "miss"):
                if winner['move1']['stars'] > 0:
                    m1 = await db_query.get_move(move1['name'])
                    note = m1['notes'].lower()

                    pn1, pn2, _m1, _m2 = await apply_status_effects(percentages1.copy(), percentages2.copy(),
                                                              [[note], []], is_boss=is_boss)
                    if not rage or 'oppo' not in note:
                        percentages1, percentages2 = pn1, pn2
                    p1_temp, p2_temp = percentages1, percentages2
                    winner['winner'] = '1'
                    winner['status_effect'] = note
                    winner['move1']['msg'] = _m1
                elif move2['color'] == 'white' and winner['move2']['dmg'] > 0:
                    winner['winner'] = '2'
                    winner['status_effect'] = '@sc'
                    winner['move2'][
                        'msg'] = f'''{z1['name2']}'s {move1['name']} was ineffective because it has 0 stars! {z2['name2']}'s {move2['name']} breaks through with ease!'''
                else:
                    winner['winner'] = ""
                    winner['status_effect'] = '@sc'
                    winner['move1'][
                        'msg'] = f'''{z1['name2']}'s {move1['name']} was ineffective because it has 0 stars!'''

            case ("blue", "white") | ("blue", "gold") | ("blue", "purple") | ("blue", "miss") | ("white", "blue") | (
                "gold",
                "blue") | (
                     "purple", "blue") | ("miss", "blue") | ("blue", "blue"):

                winner['winner'] = ""

            case ("white", "miss") | ("gold", "miss"):
                if winner['move1']['dmg'] == 0:
                    winner['winner'] = ""
                else:
                    winner['winner'] = '1'

            case ("miss", "white") | ("miss", "gold"):
                if winner['move2']['dmg'] == 0:
                    winner['winner'] = ""
                else:
                    winner['winner'] = '2'

            case ("gold", "purple"):
                m2 = await db_query.get_move(move2['name'])
                note = m2['notes'].lower()
                if winner['move2']['stars'] > 0 and 'knock' in note and 'against' in note and 'gold' in note:
                    winner['winner'] = '2'
                else:
                    if winner['move1']['dmg'] == 0:
                        if winner['move2']['stars'] > 0:

                            percentages1, percentages2, _m1, _m2 = await apply_status_effects(percentages1, percentages2,
                                                                                        [[], [note]])
                            p1_temp, p2_temp = percentages1, percentages2
                            winner['winner'] = '2'
                            winner['status_effect'] = note
                            # winner['status_effect'] = note if not rage else 'knock out'
                            winner['move2']['msg'] = _m2
                        else:
                            winner['winner'] = ""
                    else:
                        winner['winner'] = '1'

            case ("purple", "gold"):
                m1 = await db_query.get_move(move1['name'])
                note = m1['notes'].lower()
                if winner['move1']['stars'] > 0 and 'knock' in note and 'against' in note and 'gold' in note:
                    winner['winner'] = '1'
                else:
                    if winner['move2']['dmg'] == 0:
                        if winner['move1']['stars'] > 0:
                            pn1, pn2, _m1, _m2 = await apply_status_effects(percentages1.copy(), percentages2.copy(),
                                                                      [[note], []], is_boss=is_boss)
                            if not rage or 'oppo' not in note:
                                percentages1, percentages2 = pn1, pn2
                            p1_temp, p2_temp = percentages1, percentages2
                            winner['winner'] = '1'
                            winner['status_effect'] = note
                            winner['move1']['msg'] = _m1
                        else:
                            winner['winner'] = ""
                    else:
                        winner['winner'] = '2'

            case ("purple", "purple"):
                s1 = winner['move1']['stars']
                s2 = winner['move2']['stars']
                if s1 > s2:
                    m1 = await db_query.get_move(move1['name'])

                    pn1, pn2, _m1, _m2 = await apply_status_effects(percentages1.copy(), percentages2.copy(),
                                                              [[m1['notes']], []],
                                                              is_boss=is_boss)
                    if not rage or 'oppo' not in m1['notes']:
                        percentages1, percentages2 = pn1, pn2
                    p1_temp, p2_temp = percentages1, percentages2
                    winner['winner'] = '1'
                    winner['status_effect'] = m1['notes'].lower()
                    winner['move1']['msg'] = _m1

                elif s1 == s2:
                    winner["winner"] = ""  # DRAW
                else:
                    m2 = await db_query.get_move(move2['name'])
                    percentages1, percentages2, _m1, _m2 = await apply_status_effects(percentages1, percentages2,
                                                                                [[], [m2['notes']]])
                    p1_temp, p2_temp = percentages1, percentages2
                    winner['winner'] = '2'
                    winner['status_effect'] = m2['notes'].lower()
                    # winner['status_effect'] = m2['notes'].lower() if not rage else 'knock out'
                    winner['move2']['msg'] = _m2

            case ("miss", "miss"):
                winner['winner'] = ""

            case _:
                print(f"IDK what this is {move1}, {move2}")
    s_e = winner.get('status_effect', 'knock')
    k_o_s_e = ('knock' in s_e and 'against' not in s_e)

    # Blue move set to trigger here
    if winner['winner'] == "2" and (
            not winner.get('z1_blue_void', False) or 'pierce' in winner.get('eq2_msg', '') or 'nullified' in winner.get(
        'eq2_msg', '')):
        if z1_blue_trigger:
            if not winner.get('z1_blue_void', False):
                winner['winner'] = ""
            if 'status_effect' in winner:
                percentages1 = pre_percentages1
                percentages2 = pre_percentages2
                p1_temp, p2_temp = percentages1, percentages2
                del winner['status_effect']
            if 'eq1_name' in winner:
                winner['eq1_msg'] = f"**{z1['name2']}** uses 🟦 **{z1['moves'][6]['name']}**!\n" + winner.get('eq1_msg',
                                                                                                              '')
            else:
                winner['eq1_name'] = ""
                winner['eq1_msg'] = f"**{z1['name2']}** uses 🟦 **{z1['moves'][6]['name']}**!"

    if winner['winner'] == "1" and (
            not winner.get('z2_blue_void', False) or 'pierce' in winner.get('eq1_msg', '') or 'nullified' in winner.get(
        'eq1_msg', '')):
        if z2_blue_trigger:
            if not winner.get('z2_blue_void', False):
                winner['winner'] = ""
            if 'status_effect' in winner:
                percentages2 = pre_percentages2
                percentages1 = pre_percentages1
                p1_temp, p2_temp = percentages1, percentages2
                del winner['status_effect']
            if 'eq1_name' in winner:
                winner['eq1_msg'] = f"**{z2['name2']}** uses 🟦 **{z2['moves'][6]['name']}**!\n" + winner.get('eq1_msg',
                                                                                                              '')
            else:
                winner['eq1_name'] = ""
                winner['eq1_msg'] = f"**{z2['name2']}** uses 🟦 **{z2['moves'][6]['name']}**!"

    for idx, eq1 in enumerate(eq1_list):
        if k_o_s_e and winner['winner'] == "2" and 'chance to survive from being knocked out' in eq1:
            new_winner = random.choices(["", "2"], [eq1_vals[idx], 100 - eq1_vals[idx]])[0]
            winner['winner'] = new_winner
            if winner['winner'] == "":
                winner['eq1_name'] = buff_eqs[0]
                winner['eq1_msg'] = winner.get('eq1_msg',
                                               '') + f"\nWoah! **{z1['name2']}** seemingly comes back to life with its **{buff_eqs[0]}**!"
    for idx, eq2 in enumerate(eq2_list):
        if k_o_s_e and winner['winner'] == "1" and 'chance to survive from being knocked out' in eq2:
            new_winner = random.choices(["", "1"], [eq2_vals[idx], 100 - eq2_vals[idx]])[0]
            winner['winner'] = new_winner
            if winner['winner'] == "":
                winner['eq2_name'] = buff_eqs[1]
                winner['eq2_msg'] = winner.get('eq2_msg',
                                               '') + f"\nWoah! **{z2['name2']}** seemingly comes back to life with its **{buff_eqs[1]}**!"

    return winner, percentages1, percentages2, status_affects, p1_temp, p2_temp


# bt = battle_zerpmons(await db_query.get_zerpmon("Fiepion"), await db_query.get_zerpmon("Elapix"), [["fire"], ["Bug", "Steel"]],
#                      [[], []], ["Dark", "Dark"], [None, None],
#                      blue_dict={'orig_b1': 0, 'orig_b2': 0, 'new_b1': 0, 'new_b2': 0})
# print(json.dumps(bt, indent=2))


async def download_image(url, path_to_file):
    if os.path.isfile(path_to_file):
        # print(f"{path_to_file} already exists, skipping download.")
        pass
    else:
        response = requests.get(url)
        with open(path_to_file, 'wb') as f:
            f.write(response.content)
        print(f"Downloaded {path_to_file}.")


async def proceed_gym_battle(interaction: nextcord.Interaction, gym_type):
    _data1 = await db_query.get_owned(interaction.user.id)
    u_flair = f' | {_data1.get("flair", [])[0]}' if len(
        _data1.get("flair", [])) > 0 else ''
    user_mention = interaction.user.mention + u_flair

    leader = await db_query.get_gym_leader(gym_type)
    gym_won = {} if 'gym' not in _data1 else _data1['gym'].get('won', {})
    stage = 1 if gym_type not in gym_won else gym_won[gym_type]['stage']
    leader_name = config.LEADER_NAMES[gym_type]
    trainer_embed = CustomEmbed(title=f"Gym Battle",
                                description=f"({user_mention} VS {leader_name} {config.TYPE_MAPPING[gym_type]})",
                                color=0xf23557)

    user1_zerpmons = _data1['zerpmons']
    tc1 = list(_data1['trainer_cards'].values())[0] if ('gym_deck' not in _data1) or (
            '0' in _data1['gym_deck'] and (not _data1['gym_deck']['0'].get('trainer', None))) else \
        _data1['trainer_cards'][_data1['gym_deck']['0']['trainer']]
    tc1i = tc1['image']
    buffed_type1 = [i['value'] for i in tc1['attributes'] if i['trait_type'] == 'Affinity' or i['trait_type'] == 'Type']

    user2_zerpmons = leader['zerpmons']
    random.shuffle(user2_zerpmons)
    tc2i = leader['image']

    path1 = f"./static/images/{tc1['name']}.png"
    path2 = f"./static/images/vs.png"
    path3 = tc2i

    url1 = tc1i if "https:/" in tc1i else 'https://cloudflare-ipfs.com/ipfs/' + tc1i.replace("ipfs://", "")
    trainer_embed.add_field(
        name=f"{tc1['name']} ({', '.join([i['value'] for i in tc1['attributes'] if i['trait_type'] == 'Affinity' or i['trait_type'] == 'Type' or i['trait_type'] == 'Status'])})",
        value="\u200B", inline=True)

    trainer_embed.add_field(name=f"🆚", value="\u200B", inline=True)

    trainer_embed.add_field(
        name=f"{leader_name} (Stage {stage})",
        value="\u200B", inline=True)

    await gen_image(str(interaction.id) + '0', url1, '', path1, path2, path3, leader['bg'])

    file2 = nextcord.File(f"{interaction.id}0.png", filename="image0.png")
    trainer_embed.set_image(url=f'attachment://image0.png')

    low_z = max(len(user1_zerpmons), len(user2_zerpmons))
    b_type = 5
    if b_type <= low_z:
        low_z = b_type

    # Sanity check
    if 'gym_deck' in _data1 and (
            len(_data1['gym_deck']) == 0 or ('0' in _data1['gym_deck'] and len(_data1['gym_deck']['0']) == 0)):
        await interaction.send(content=f"**{_data1['username']}** please check your gym battle deck, it's empty.")
    # Proceed

    print("Start")
    try:
        del _data1['gym_deck']['0']['trainer']
    except:
        pass

    if 'gym_deck' not in _data1 or (
            len(_data1['gym_deck']) == 0 or ('0' in _data1['gym_deck'] and len(_data1['gym_deck']['0']) == 0)):
        user1_zerpmons = list(user1_zerpmons.values())[:low_z if len(user1_zerpmons) > low_z else len(user1_zerpmons)]
    else:
        user1_z = []
        for i in range(5):
            try:
                temp_zerp = user1_zerpmons[_data1['gym_deck']['0'][str(i)]]
                eq = _data1['equipment_decks']['gym_deck']['0'][str(i)]
                if eq is not None and eq in _data1['equipments']:
                    eq_ = _data1['equipments'][eq]
                    temp_zerp['buff_eq'], temp_zerp['eq'] = eq_['name'], eq
                user1_z.append(temp_zerp)
            except:
                pass
        user1_z.reverse()
        user1_zerpmons = user1_z if len(user1_z) <= low_z else user1_z[-low_z:]

    # print(user1_zerpmons[-1], '\n', user2_zerpmons[-1], '\n', user1_zerpmons, '\n', user2_zerpmons, )
    gym_eq = await db_query.get_eq_by_name(gym_type, gym=True)
    gym_eq2 = None
    for _i, zerp in enumerate(user2_zerpmons):
        lvl_inc = 3 if stage > 2 else (stage - 1)
        user2_zerpmons[_i]['level'] = 10 * lvl_inc
        for i in range(lvl_inc):
            user2_zerpmons[_i] = await db_query.update_moves(user2_zerpmons[_i], save_z=False)
        if stage > 6:
            user2_zerpmons[_i]['buff_eq'], user2_zerpmons[_i]['eq'] = gym_eq['name'], gym_eq
        if stage > 10:
            gym_eq2 = await db_query.get_eq_by_name('Tattered Cloak')
            user2_zerpmons[_i]['buff_eq2'], user2_zerpmons[_i]['eq2'] = gym_eq2['name'], gym_eq2
        zerp['extra_dmg_p'] = config.GYM_DMG_BUFF[stage]
        zerp['extra_crit_p'] = config.GYM_CRIT_BUFF[stage]
    msg_hook = None
    status_stack = [[], []]
    p1 = None
    p2 = None
    p1_temp = None
    p2_temp = None
    battle_log = {'teamA': {'trainer': tc1, 'zerpmons': []},
                  'teamB': {'trainer': {'name': leader_name}, 'zerpmons': []}, 'battle_type': 'Gym Battle'}
    set_zerp_extra_meta(user1_zerpmons)
    set_zerp_extra_meta(user2_zerpmons)
    while len(user1_zerpmons) != 0 and len(user2_zerpmons) != 0:
        z1 = user1_zerpmons[-1]
        z1_obj = await db_query.get_zerpmon(z1['name'], user_id=interaction.user.id)
        z1['name2'] = z1_obj['name2']
        z1_moves = z1_obj['moves']

        z1_type = [i['value'] for i in z1['attributes'] if i['trait_type'] == 'Type']
        buffed_zerp = ''
        for idx, i in enumerate(z1_type):
            if 'Dragon' in i:
                z1_type[idx] = 'Dragon'
                i = 'Dragon'
            if i in buffed_type1:
                buffed_zerp = i
            elif tc1 and tc1.get('nft_id', '') in OMNI_TRAINERS:
                buffed_zerp = i
                break

        z2 = user2_zerpmons[-1]
        z2_moves = z2['moves']
        z2_type = [i['value'] for i in z2['attributes'] if i['trait_type'] == 'Type']
        if 'buff_eq' in z1:
            eq1 = _data1['equipments'][z1['eq']]
            types1 = {}
            for m_i in range(4):
                types1[z1_obj['moves'][m_i]['type']] = 1
            eq_type = [_i['value'] for _i in eq1['attributes'] if _i['trait_type'] == 'Type'][-1]
            if eq_type not in list(types1.keys()) and eq_type != 'Omni':
                del z1['buff_eq']

        if p2 is None:
            p2 = [(float(p['percent']) if (p['percent'] not in ["0.00", "0", ""] and p['color'] != 'blue') else None)
                  for p in
                  z2['moves']]
        # buffed_type2 = [gym_type] if stage > 12 else []
        buffed_type2 = []
        main_embed, file, p1, p2, eq1_list, eq2_list, updated_blue_dict = await get_zerp_battle_embed(interaction, z1, z2,
                                                                                                z1_obj,
                                                                                                z2, z1_type,
                                                                                                z2_type, [buffed_type1,
                                                                                                          buffed_type2],
                                                                                                buffed_zerp,
                                                                                                # gym_type if stage > 12 else '',
                                                                                                '',
                                                                                                leader['bg'],
                                                                                                p1.copy() if p1 is not None else p1,
                                                                                                p2.copy() if p2 is not None else p2)
        await asyncio.sleep(1)
        if msg_hook is None:
            msg_hook = interaction
            await interaction.send(content="\u200B", embeds=[trainer_embed, main_embed], files=[file2, file],
                                   ephemeral=True)
        else:
            await msg_hook.send(content="\u200B", embed=main_embed, file=file, ephemeral=True)

        eliminate = ""
        move_counter = 0
        is_reroll = None
        move1_cached, move2_cached = {}, {}
        while eliminate == "":
            await asyncio.sleep(1)
            # If battle lasts long then end it
            if move_counter == 20:
                r_int = random.randint(1, 2)
                rand_loser = z2['name'] if r_int == 2 else z1['name']
                await msg_hook.send(
                    content=f"Out of nowhere, a giant **meteor** lands right on top of 💀 {rand_loser} 💀!",
                    ephemeral=True)
                eliminate = (r_int, rand_loser)
                if r_int == 2:
                    p2 = None
                    status_stack[0] = [i for i in status_stack[0] if ('oppo' not in i) and ('enemy' not in i)]
                    status_stack[1] = [i for i in status_stack[1] if ('oppo' in i) or ('enemy' in i)]
                    await db_query.save_zerpmon_winrate(z1['name'], z2['name'])
                elif r_int == 1:
                    p1 = None
                    status_stack[1] = [i for i in status_stack[1] if ('oppo' not in i) and ('enemy' not in i)]
                    status_stack[0] = [i for i in status_stack[0] if ('oppo' in i) or ('enemy' in i)]
                    await db_query.save_zerpmon_winrate(z2['name'], z1['name'])
                break

            result, p1, p2, status_stack, p1_temp, p2_temp = await battle_zerpmons((interaction.user.id, z1_obj), z2,
                                                                             [z1_type, z2_type],
                                                                             status_stack,
                                                                             [eq1_list, eq2_list],
                                                                             [z1.get('buff_eq', None),
                                                                              z2.get('buff_eq', None)], p1, p2,
                                                                             p1_temp, p2_temp,
                                                                             blue_dict=updated_blue_dict,
                                                                             idx1=None if is_reroll != 2 else move1_cached,
                                                                             idx2=None if is_reroll != 1 else move2_cached)
            t_info1 = config.TYPE_MAPPING[result['move1']['type'].replace(" ", '')] + ' ' + result['move1']['mul']
            t_info2 = config.TYPE_MAPPING[result['move2']['type'].replace(" ", '')] + ' ' + result['move2']['mul']
            t_info1 = f'({t_info1})' if t_info1 not in ["", " "] else t_info1
            t_info2 = f'({t_info2})' if t_info2 not in ["", " "] else t_info2

            dmg1_str = f"{result['move1']['name']} {result['move1']['stars'] * '★'} (__{result['move1']['percent']}%__)" if \
                result['move1']['stars'] != '' \
                else f"{result['move1']['name']}{'ed' if result['move1']['color'] == 'miss' else f' {t_info1} ' + str(result['move1']['dmg']) if 'dmg_str1' not in result else result['dmg_str1']} (__{result['move1']['percent']}%__)"

            dmg2_str = f"{result['move2']['name']} {result['move2']['stars'] * '★'} (__{result['move2']['percent']}%__)" if \
                result['move2']['stars'] != '' \
                else f"{result['move2']['name']}{'ed' if result['move2']['color'] == 'miss' else f' {t_info2} ' + str(result['move2']['dmg']) if 'dmg_str2' not in result else result['dmg_str2']} (__{result['move2']['percent']}%__)"
            s1 = f"**{z1['name2']}**\t({', '.join([config.TYPE_MAPPING[i] for i in z1_type])})\t{' used' if result['move1']['color'] != 'miss' else ''} " \
                 f"{config.COLOR_MAPPING[result['move1']['color']]}  {dmg1_str}\n"
            s2 = f"**{z2['name2']}**\t({', '.join([config.TYPE_MAPPING[i] for i in z2_type])})\t{' used' if result['move2']['color'] != 'miss' else ''} " \
                 f"{config.COLOR_MAPPING[result['move2']['color']]}  {dmg2_str}\n"

            atk_msg = apply_reroll_to_msg(is_reroll, result, s1, s2, move1_cached, move2_cached)

            await msg_hook.send(content=atk_msg, ephemeral=True)
            await asyncio.sleep(1)
            pre_text = (f"{result['eq1_msg']}\n" if 'eq1_name' in result else '') + (
                f"{result['eq2_msg']}\n" if 'eq2_name' in result else '')

            skip, old_status, is_reroll = await set_reroll(msg_hook, pre_text, result, is_reroll, move1_cached,
                                                           move2_cached)
            if skip:
                continue
            is_reroll = None

            for i, effect in enumerate(status_stack[0].copy()):
                if '0 damage' in effect:
                    status_stack[0].remove(effect)
                    break
            for i, effect in enumerate(status_stack[1].copy()):
                if '0 damage' in effect:
                    status_stack[1].remove(effect)
                    break

            print(result)

            # purple attacks
            if 'status_effect' in result:
                effect = result['status_effect']
                if result['winner'] == '1':
                    if 'next' in effect:
                        if 'next attack' in effect:
                            status_stack[0].append(effect)
                            p_x = get_val(effect)
                            count_x = status_stack[0].count(effect)
                            if 'decrease' in effect:
                                new_m = f"**{z2['name2']}**'s damage is reduced by (**{p_x}**%) for the next {'' if count_x <= 1 else ('**' + str(count_x) + '** ')}{'attack' if count_x <= 1 else 'attacks'}!"
                            else:
                                new_m = f"**{z1['name2']}**'s damage is increased by (**{p_x * count_x}**%) for the next attack!"

                            await msg_hook.send(
                                content=pre_text + new_m, ephemeral=True)
                            move_counter += 1
                            continue
                        elif '0 damage' in effect:
                            if '2' in effect:
                                status_stack[0].append(effect)
                                status_stack[0].append(effect)
                                count_x = status_stack[0].count(effect)
                                new_m = f"**{z2['name2']}**'s damage reduced to 0 for **{count_x}** {'turns' if count_x > 1 else 'turn'}!"
                                await msg_hook.send(
                                    content=pre_text + new_m, ephemeral=True)
                            else:
                                status_stack[0].append(effect)
                                count_x = status_stack[0].count(effect)
                                new_m = f"**{z2['name2']}**'s damage reduced to 0 for **{count_x}** {'turns' if count_x > 1 else 'turn'}!"
                                await msg_hook.send(
                                    content=pre_text + new_m, ephemeral=True)

                        move_counter += 1
                        continue
                    elif 'knock' in effect:
                        if 'against' not in effect:
                            result['winner'] = '1'
                        else:
                            if result['move2']['color'] in effect:
                                result['winner'] = '1'
                            else:
                                new_m = f"{result['move1']['name']} was ineffective! Draw!"
                                await msg_hook.send(
                                    content=pre_text + new_m, ephemeral=True)
                                move_counter += 1
                                continue
                    elif 'reduce' in effect and 'star' in effect:
                        status_stack[0].append(effect)
                        new_m = f"reduced {z2['name2']}'s Purple stars to 0 for the rest of the combat!"
                        await msg_hook.send(
                            content=pre_text + new_m, ephemeral=True)
                        move_counter += 1
                        continue
                    else:
                        if effect == '@sc':
                            new_m = result['move1']['msg']
                        else:
                            new_m = result['move1']['msg'][:-1]
                            i = int(result['move1']['msg'][-1])

                            new_m = new_m.replace(config.COLOR_MAPPING[z1_moves[i]['color']], '').replace(
                                config.COLOR_MAPPING[z2_moves[i]['color']], '')
                            new_m = new_m.replace("@me",
                                                  ' ' + z1['name2'] + '\'s ' + z1_moves[i]['name'] + '  ').replace(
                                "@op", ' ' + z2['name2'] + '\'s ' + z2_moves[i]['name'] + '  ')
                            new_m += f" ({str(z1_moves[i]['dmg']) + 'dmg, ' if 'dmg' in z1_moves[i] and z1_moves[i]['dmg'] != '' else ''}{(str(round(float(p2[i]))) if p2[i] is not None else 0) if 'opposing' in result['status_effect'] else (str(round(float(p1[i]))) if p1[i] is not None else 0)}%)"
                        await msg_hook.send(
                            content=pre_text + new_m, ephemeral=True)
                        move_counter += 1
                        if effect != '@sc':
                            continue
                elif result['winner'] == '2':
                    if 'next' in effect:
                        if 'next attack' in effect:
                            status_stack[1].append(effect)
                            p_x = get_val(effect)
                            count_x = status_stack[1].count(effect)
                            if 'decrease' in effect:
                                new_m = f"**{z1['name2']}**'s damage is reduced by (**{p_x}**%) for the next {'' if count_x <= 1 else ('**' + str(count_x) + '** ')}{'attack' if count_x <= 1 else 'attacks'}!"
                            else:
                                new_m = f"**{z2['name2']}**'s damage is increased by (**{p_x * count_x}**%) for the next attack!"
                            await msg_hook.send(
                                content=pre_text + new_m, ephemeral=True)
                            move_counter += 1
                            continue
                        elif '0 damage' in effect:
                            if '2' in effect:
                                status_stack[1].append(effect)
                                status_stack[1].append(effect)
                                count_x = status_stack[1].count(effect)
                                new_m = f"**{z1['name2']}**'s damage reduced to 0 for **{count_x}** {'turns' if count_x > 1 else 'turn'}!"
                                await msg_hook.send(
                                    content=pre_text + new_m, ephemeral=True)
                            else:
                                status_stack[1].append(effect)
                                count_x = status_stack[1].count(effect)
                                new_m = f"**{z1['name2']}**'s damage reduced to 0 for **{count_x}** {'turns' if count_x > 1 else 'turn'}!"
                                await msg_hook.send(
                                    content=pre_text + new_m, ephemeral=True)
                        move_counter += 1
                        continue
                    elif 'knock' in effect:
                        if 'against' not in effect:
                            result['winner'] = '2'
                        else:
                            if result['move1']['color'] in effect:
                                result['winner'] = '2'
                            else:
                                new_m = f"{result['move2']['name']} was ineffective! Draw!"
                                await msg_hook.send(
                                    content=pre_text + new_m, ephemeral=True)
                                move_counter += 1
                                continue
                    elif 'reduce' in effect and 'star' in effect:
                        status_stack[1].append(effect)
                        new_m = f"reduced {z1['name2']}'s Purple stars to 0 for the rest of the combat!"
                        await msg_hook.send(
                            content=pre_text + new_m, ephemeral=True)
                        move_counter += 1
                        continue
                    else:
                        if effect == '@sc':
                            new_m = result['move2']['msg']
                        else:
                            new_m = result['move2']['msg'][:-1]
                            i = int(result['move2']['msg'][-1])

                            new_m = new_m.replace(config.COLOR_MAPPING[z1_moves[i]['color']], '').replace(
                                config.COLOR_MAPPING[z2_moves[i]['color']], '')
                            new_m = new_m.replace("@me",
                                                  ' ' + z2['name2'] + '\'s ' + z2_moves[i]['name'] + '  ').replace(
                                "@op", ' ' + z1['name2'] + '\'s ' + z1_moves[i]['name'] + '  ')
                            new_m += f" ({str(z2_moves[i]['dmg']) + 'dmg, ' if 'dmg' in z2_moves[i] and z2_moves[i]['dmg'] != '' else ''}{(str(round(float(p1[i]))) if p1[i] is not None else 0) if 'opposing' in result['status_effect'] else (str(round(float(p2[i]))) if p2[i] is not None else 0)}%)"

                        await msg_hook.send(
                            content=pre_text + new_m, ephemeral=True)
                        move_counter += 1
                        if effect != '@sc':
                            continue

            # DRAW
            if result['winner'] == "":
                await msg_hook.send(
                    content=(f"{result['eq1_msg']}\n" if 'eq1_name' in result else '') + (
                        f"{result['eq2_msg']}\n" if 'eq2_name' in result else '') + f"**DRAW**",
                    ephemeral=True)
                move_counter += 1
                continue
            # {}'s "Crystal Ball" activated and nullified {} attack!
            if result['winner'] == '1':
                await msg_hook.send(
                    content=(f"{result['eq1_msg']}\n" if "eq1_name" in result else '') + (
                        f"{result['eq2_msg']}\n" if "eq2_name" in result else '')
                            + (f"{z1['name2']} **knocked out** 💀 {z2['name2']} 💀!" if '🎯' not in result['move1'][
                        'mul'] else f"{random.choice(config.CRIT_STATEMENTS).format(loser=z2['name2'])}"),
                    ephemeral=True)
                eliminate = (2, z2['name'])
                status_stack[0] = [i for i in status_stack[0] if ('oppo' not in i) and ('enemy' not in i)]
                status_stack[1] = [i for i in status_stack[1] if ('oppo' in i) or ('enemy' in i)]
                await db_query.save_zerpmon_winrate(z1['name'], z2['name'])
                move_counter += 1

            elif result['winner'] == '2':
                await msg_hook.send(
                    content=(f"{result['eq1_msg']}\n" if "eq1_name" in result else '') + (
                        f"{result['eq2_msg']}\n" if "eq2_name" in result else '')
                            + (f"{z2['name2']} **knocked out** 💀 {z1['name2']} 💀!" if '🎯' not in result['move2'][
                        'mul'] else f"{random.choice(config.CRIT_STATEMENTS).format(loser=z1['name2'])}"),
                    ephemeral=True)
                eliminate = (1, z1['name'])
                status_stack[1] = [i for i in status_stack[1] if ('oppo' not in i) and ('enemy' not in i)]
                status_stack[0] = [i for i in status_stack[0] if ('oppo' in i) or ('enemy' in i)]
                await db_query.save_zerpmon_winrate(z2['name'], z1['name'])
                move_counter += 1

        if eliminate[0] == 1:
            z1['rounds'].append(0)
            z2['rounds'].append(1)
            battle_log['teamA']['zerpmons'].append({'name': z1['name'],
                                                    'ko_move':  result['move2']['name'] + ' ' + config.TYPE_MAPPING[
                                                        result['move2']['type']], 'rounds': z1['rounds'].copy()})
            user1_zerpmons = [i for i in user1_zerpmons if i['name'] != eliminate[1]]
            p2 = await remove_effects(p2, p1, eq1_list, z2=z2)
            p1 = None
            p1_temp = None
        elif eliminate[0] == 2:
            z1['rounds'].append(1)
            z2['rounds'].append(0)
            battle_log['teamB']['zerpmons'].append({'name': z2['name'],
                                                    'ko_move': result['move1']['name'] + ' ' + config.TYPE_MAPPING[
                                                        result['move1']['type']], 'rounds': z2['rounds'].copy()})
            user2_zerpmons = [i for i in user2_zerpmons if i['name'] != eliminate[1]]

            p1 = await remove_effects(p1, p2, eq2_list, z1=z1_obj)
            p2 = None
            p2_temp = None
        file.close()
        for i in range(3):
            try:
                os.remove(f"{msg_hook.id}.png")
                break
            except Exception as e:
                print(f"Delete failed retrying {e}")

    file2.close()
    for i in range(3):
        try:
            os.remove(f"{msg_hook.id}0.png")
            break
        except Exception as e:
            print(f"Delete failed retrying {e}")

    total_gp = 0 if "gym" not in _data1 else _data1["gym"].get("gp", 0) + stage
    if len(user1_zerpmons) == 0:
        await interaction.send(
            f"Sorry you **LOST** 💀 \nYou can try battling **{leader_name}** again tomorrow",
            ephemeral=True)
        battle_log['teamB']['zerpmons'].append({'name': z2['name'], 'rounds': z2['rounds']})
        await db_query.update_battle_log(interaction.user.id, None, interaction.user.name, leader_name, battle_log['teamA'],
                                   battle_log['teamB'], winner=2, battle_type=battle_log['battle_type'])
        # Save user's match
        await db_query.add_gp_queue(_data1['address'], _data1['gym'].get('match_cnt', 0) if 'gym' in _data1 else 1,
                                    0)
        await db_query.update_gym_won(_data1['discord_id'], _data1.get('gym', {}), gym_type, stage, lost=True)
        await asyncio.sleep(1)
        return 2
    elif len(user2_zerpmons) == 0:
        # Add GP to user
        battle_log['teamA']['zerpmons'].append(
            {'name': z1['name'], 'rounds': z1['rounds']})
        await db_query.update_battle_log(interaction.user.id, None, interaction.user.name, leader_name, battle_log['teamA'],
                                   battle_log['teamB'], winner=1, battle_type=battle_log['battle_type'])

        zrp_reward = await db_query.add_gp_queue(_data1['address'], _data1['gym'].get('match_cnt', 0) if 'gym' in _data1 else 1, stage)
        await db_query.update_gym_won(_data1['discord_id'], _data1.get('gym', {}), gym_type, stage, lost=False)
        embed = CustomEmbed(title="Match Result", colour=0xa4fbe3,
                            description=f"{user_mention} vs {leader_name} {config.TYPE_MAPPING[gym_type]}")

        embed.add_field(name='\u200B', value='\u200B')
        embed.add_field(name='🏆 WINNER 🏆',
                        value=user_mention,
                        inline=False)
        embed.add_field(
            name=f"GP",
            value=f"{stage}  ⬆",
            inline=False)
        embed.add_field(name=f'Total', value=total_gp,
                        inline=False)
        # response, qty, reward = await xrpl_ws.reward_gym(_data1['discord_id'], stage)
        # if reward == "ZRP":
        embed.add_field(name='ZRP Won', value=zrp_reward, inline=True)
        await msg_hook.send(
            f"**WINNER**   👑**{user_mention}**👑", embed=embed, ephemeral=True)
        await asyncio.sleep(1)
        # if not response:
        #
        #     await interaction.send(
        #         f"**Failed**, something went wrong.",
        #         ephemeral=True)
        # else:
        await interaction.send(
            f"**Successfully** added transaction to queue (`{zrp_reward}` ZRP)",
            ephemeral=True)
        return 1


async def proceed_battle(message: nextcord.Message, battle_instance, b_type=5, battle_name='Friendly Battle',
                         p1_deck=None, p2_deck=None, hidden=False):
    uid1 = battle_instance["challenger"]
    uid2 = battle_instance["challenged"]
    _data1 = await db_query.get_owned(uid1)
    _data2 = await db_query.get_owned(uid2)
    if p1_deck is not None:
        z1_deck, eq1_deck = p1_deck.get('z'), p1_deck.get('e')
        print('P1 deck', p1_deck)
        _data1['battle_deck']['0'] = z1_deck.copy()
        _data1['equipment_decks']['battle_deck']['0'] = eq1_deck.copy()
    if p2_deck is not None:
        z2_deck, eq2_deck = p2_deck.get('z'), p2_deck.get('e')
        print('P2 deck', p2_deck)
        _data2['battle_deck']['0'] = z2_deck.copy()
        _data2['equipment_decks']['battle_deck']['0'] = eq2_deck.copy()
    user1_zerpmons = _data1['zerpmons']
    user2_zerpmons = _data2['zerpmons']

    if battle_instance['type'] != 'free_br':
        trainer_embed = CustomEmbed(title=f"Trainers Battle",
                                    description=f"({battle_instance['username1']} VS {battle_instance['username2']})",
                                    color=0xf23557)

        tc1 = list(_data1['trainer_cards'].values())[0] if ('battle_deck' not in _data1) or (
                '0' in _data1['battle_deck'] and (not _data1['battle_deck']['0'].get('trainer', None))) else \
            _data1['trainer_cards'][_data1['battle_deck']['0']['trainer']]
        tc1i = tc1['image']
        buffed_type1 = [i['value'] for i in tc1['attributes'] if
                        i['trait_type'] == 'Affinity' or i['trait_type'] == 'Type']

        tc2 = list(_data2['trainer_cards'].values())[0] if ('battle_deck' not in _data2) or (
                '0' in _data2['battle_deck'] and (not _data2['battle_deck']['0'].get('trainer', None))) else \
            _data2['trainer_cards'][_data2['battle_deck']['0']['trainer']]
        tc2i = tc2['image']
        buffed_type2 = [i['value'] for i in tc2['attributes'] if
                        i['trait_type'] == 'Affinity' or i['trait_type'] == 'Type']

        path1 = f"./static/images/{tc1['name']}.png"
        path2 = f"./static/images/vs.png"
        path3 = f"./static/images/{tc2['name']}.png"

        url1 = tc1i if "https:/" in tc1i else 'https://cloudflare-ipfs.com/ipfs/' + tc1i.replace("ipfs://", "")
        trainer_embed.add_field(
            name=f"{tc1['name']} ({', '.join([i['value'] for i in tc1['attributes'] if i['trait_type'] == 'Affinity' or i['trait_type'] == 'Type' or i['trait_type'] == 'Status'])})",
            value="\u200B", inline=True)

        trainer_embed.add_field(name=f"🆚", value="\u200B", inline=True)

        url2 = tc2i if "https:/" in tc2i else 'https://cloudflare-ipfs.com/ipfs/' + tc2i.replace("ipfs://", "")
        trainer_embed.add_field(
            name=f"{tc2['name']} ({', '.join([i['value'] for i in tc2['attributes'] if i['trait_type'] == 'Affinity' or i['trait_type'] == 'Type' or i['trait_type'] == 'Status'])})",
            value="\u200B", inline=True)

        bg_img1 = _data1.get('bg', [])
        bg_img2 = _data2.get('bg', [])
        bg_img = None
        if bg_img1 and bg_img2:
            bg_img = random.choice([bg_img1[0], bg_img2[0]])
        else:
            bg_img = bg_img1[0] if bg_img1 else (bg_img2[0] if bg_img2 else None)
        if 'Ranked' in battle_name:
            bg_img = config.RANK_IMAGES[b_type]
        await gen_image(str(message.id) + '0', url1, url2, path1, path2, path3, gym_bg=bg_img)

        file2 = nextcord.File(f"{message.id}0.png", filename="image0.png")
        trainer_embed.set_image(url=f'attachment://image0.png')

        low_z = max(len(user1_zerpmons), len(user2_zerpmons))
        if b_type <= low_z:
            low_z = b_type

        # Sanity check
        if 'battle_deck' in _data1 and (
                len(_data1['battle_deck']) == 0 or (
                '0' in _data1['battle_deck'] and len(_data1['battle_deck']['0']) == 0)):
            await message.reply(content=f"**{_data1['username']}** please check your battle deck, it's empty.")
        elif 'battle_deck' in _data2 and (
                len(_data2['battle_deck']) == 0 or (
                '0' in _data2['battle_deck'] and len(_data2['battle_deck']['0']) == 0)):
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
        if 'battle_deck' not in _data1 or (
                len(_data1['battle_deck']) == 0 or (
                '0' in _data1['battle_deck'] and len(_data1['battle_deck']['0']) == 0)):
            user1_zerpmons = list(user1_zerpmons.values())[
                             :low_z if len(user1_zerpmons) > low_z else len(user1_zerpmons)]
        else:
            user1_z = []
            for i in range(5):
                try:
                    temp_zerp = user1_zerpmons[_data1['battle_deck']['0'][str(i)]]
                    eq = _data1['equipment_decks']['battle_deck']['0'][str(i)]
                    if eq is not None and eq in _data1['equipments']:
                        eq_ = _data1['equipments'][eq]
                        temp_zerp['buff_eq'], temp_zerp['eq'] = eq_['name'], eq
                    user1_z.append(temp_zerp)
                except:
                    # print(f'{traceback.format_exc()}')
                    pass
            user1_z.reverse()
            user1_zerpmons = user1_z if len(user1_z) <= low_z else user1_z[-low_z:]
        if 'battle_deck' not in _data2 or (
                len(_data2['battle_deck']) == 0 or (
                '0' in _data2['battle_deck'] and len(_data2['battle_deck']['0']) == 0)):
            user2_zerpmons = list(user2_zerpmons.values())[
                             :low_z if len(user2_zerpmons) > low_z else len(user2_zerpmons)]
        else:
            user2_z = []
            for i in range(5):
                try:
                    temp_zerp2 = user2_zerpmons[_data2['battle_deck']['0'][str(i)]]
                    eq = _data2['equipment_decks']['battle_deck']['0'][str(i)]
                    if eq is not None and eq in _data2['equipments']:
                        eq_ = _data2['equipments'][eq]
                        temp_zerp2['buff_eq'], temp_zerp2['eq'] = eq_['name'], eq
                    user2_z.append(temp_zerp2)
                except:
                    # print(f'{traceback.format_exc()}')
                    pass
            user2_z.reverse()
            user2_zerpmons = user2_z if len(user2_z) <= low_z else user2_z[-low_z:]
        battle_log = {'teamA': {'trainer': tc1, 'zerpmons': []},
                      'teamB': {'trainer': tc2, 'zerpmons': []}, 'battle_type': battle_name}

    else:
        tc1, tc2 = None, None
        user1_zerpmons = [user1_zerpmons[battle_instance['z1']]] if type(battle_instance['z1']) is str else [
            battle_instance['z1']]
        user2_zerpmons = [user2_zerpmons[battle_instance['z2']]] if type(battle_instance['z2']) is str else [
            battle_instance['z2']]
        battle_log = {'teamA': {'trainer': None, 'zerpmons': []},
                      'teamB': {'trainer': None, 'zerpmons': []}, 'battle_type': battle_name}
        buffed_type1 = []
        buffed_type2 = []
        bg_img = None
    # print(user1_zerpmons[-1], '\n', user2_zerpmons[-1], '\n', user1_zerpmons, '\n', user2_zerpmons, )
    set_zerp_extra_meta(user1_zerpmons)
    set_zerp_extra_meta(user2_zerpmons)
    msg_hook = None

    status_stack = [[], []]
    p1 = None
    p2 = None
    p1_temp = None
    p2_temp = None
    while len(user1_zerpmons) != 0 and len(user2_zerpmons) != 0:
        z1 = user1_zerpmons[-1] if len(user1_zerpmons) != 1 else deepcopy(user1_zerpmons[-1])
        z1_obj = await db_query.get_zerpmon(z1['name'], user_id=uid1, pvp=True)
        z1['name2'] = z1_obj['name2']
        z1_moves = z1_obj['moves']
        z1_type = [i['value'] for i in z1['attributes'] if i['trait_type'] == 'Type']
        buffed_zerp1 = ''
        for idx, i in enumerate(z1_type):
            if 'Dragon' in i:
                z1_type[idx] = 'Dragon'
                i = 'Dragon'
            if i in buffed_type1:
                buffed_zerp1 = i
            elif tc1 and tc1.get('nft_id', '') in OMNI_TRAINERS:
                buffed_zerp1 = i
                break

        if 'buff_eq' in z1:
            eq1 = _data1['equipments'][z1['eq']]
            types1 = {}
            for m_i in range(4):
                types1[z1_obj['moves'][m_i]['type']] = 1
            eq_type = [_i['value'] for _i in eq1['attributes'] if _i['trait_type'] == 'Type'][-1]
            if eq_type not in list(types1.keys()) and eq_type != 'Omni':
                del z1['buff_eq']

        z2 = user2_zerpmons[-1] if len(user2_zerpmons) != 1 else deepcopy(user2_zerpmons[-1])
        print(z1, z2)
        z2_obj = await db_query.get_zerpmon(z2['name'], user_id=uid2, pvp=True)
        z2['name2'] = z2_obj['name2']
        z2_moves = z2_obj['moves']
        z2_type = [i['value'] for i in z2['attributes'] if i['trait_type'] == 'Type']
        buffed_zerp2 = ''
        for idx, i in enumerate(z2_type):
            if 'Dragon' in i:
                z2_type[idx] = 'Dragon'
                i = 'Dragon'
            if i in buffed_type2:
                buffed_zerp2 = i
            elif tc2 and tc2.get('nft_id', '') in OMNI_TRAINERS:
                buffed_zerp2 = i
                break
        if 'buff_eq' in z2:
            eq2 = _data2['equipments'][z2['eq']]
            types2 = {}
            for m_i in range(4):
                types2[z2_obj['moves'][m_i]['type']] = 1
            eq_type = [_i['value'] for _i in eq2['attributes'] if _i['trait_type'] == 'Type'][-1]
            if eq_type not in list(types2.keys()) and eq_type != 'Omni':
                del z2['buff_eq']

        main_embed, file, p1, p2, eq1_list, eq2_list, updated_blue_dict = await get_zerp_battle_embed(message, z1, z2,
                                                                                                z1_obj,
                                                                                                z2_obj, z1_type,
                                                                                                z2_type,
                                                                                                [buffed_type1,
                                                                                                 buffed_type2],
                                                                                                buffed_zerp1,
                                                                                                buffed_zerp2, bg_img,
                                                                                                p1, p2, )
        if battle_instance['type'] == 'free_br':
            main_embed.description = f'{battle_instance["username1"]} vs {battle_instance["username2"]}'

        await asyncio.sleep(1)
        free_br = False
        if battle_instance['type'] == 'free_br':
            free_br = True
        if msg_hook is None:
            if hidden:
                msg_hook = message
            else:
                msg_hook = message.channel
            if 'Battle Royale' in battle_name:
                main_embed.clear_fields()
                show_view = await get_battle_view(msg_hook, z1['name'], z2['name'])
            else:
                show_view = nextcord.ui.View()
            print(show_view)
            await send_message(msg_hook, hidden, content="\u200B",
                               embeds=[main_embed] if free_br else [trainer_embed, main_embed],
                               files=[file] if free_br else [file2, file], view=show_view)
        else:
            await send_message(msg_hook, hidden, content="\u200B", embeds=[main_embed], files=[file], view=show_view)

        eliminate = ""
        move_counter = 0
        is_reroll = None
        move1_cached, move2_cached = {}, {}
        while eliminate == "":
            await asyncio.sleep(2)
            # If battle lasts long then end it
            if move_counter == 20:
                r_int = random.randint(1, 2)
                rand_loser = z2['name'] if r_int == 2 else z1['name']
                await send_message(msg_hook, hidden, embeds=[], files=[],
                                   content=f"Out of nowhere, a giant **meteor** lands right on top of 💀 {rand_loser} 💀!", )
                eliminate = (r_int, rand_loser)
                if r_int == 2:
                    p2 = None
                    status_stack[0] = [i for i in status_stack[0] if ('oppo' not in i) and ('enemy' not in i)]
                    status_stack[1] = [i for i in status_stack[1] if ('oppo' in i) or ('enemy' in i)]
                    await db_query.save_zerpmon_winrate(z1['name'], z2['name'])
                elif r_int == 1:
                    p1 = None
                    status_stack[1] = [i for i in status_stack[1] if ('oppo' not in i) and ('enemy' not in i)]
                    status_stack[0] = [i for i in status_stack[0] if ('oppo' in i) or ('enemy' in i)]
                    await db_query.save_zerpmon_winrate(z2['name'], z1['name'])
                break
            result, p1, p2, status_stack, p1_temp, p2_temp = await battle_zerpmons((uid1, z1_obj), (uid2, z2_obj),
                                                                             [z1_type, z2_type],
                                                                             status_stack,
                                                                             [eq1_list, eq2_list],
                                                                             [z1.get('buff_eq', None),
                                                                              z2.get('buff_eq', None)], p1, p2,
                                                                             p1_temp, p2_temp,
                                                                             blue_dict=updated_blue_dict,
                                                                             idx1=None if is_reroll != 2 else move1_cached,
                                                                             idx2=None if is_reroll != 1 else move2_cached)
            t_info1 = config.TYPE_MAPPING[result['move1']['type'].replace(" ", '')] + ' ' + result['move1']['mul']
            t_info2 = config.TYPE_MAPPING[result['move2']['type'].replace(" ", '')] + ' ' + result['move2']['mul']
            t_info1 = f'({t_info1})' if t_info1 not in ["", " "] else t_info1
            t_info2 = f'({t_info2})' if t_info2 not in ["", " "] else t_info2

            dmg1_str = f"{result['move1']['name']} {result['move1']['stars'] * '★'} (__{result['move1']['percent']}%__)" if \
                result['move1']['stars'] != '' \
                else f"{result['move1']['name']}{'ed' if result['move1']['color'] == 'miss' else f' {t_info1} ' + str(result['move1']['dmg']) if 'dmg_str1' not in result else result['dmg_str1']} (__{result['move1']['percent']}%__)"

            dmg2_str = f"{result['move2']['name']} {result['move2']['stars'] * '★'} (__{result['move2']['percent']}%__)" if \
                result['move2']['stars'] != '' \
                else f"{result['move2']['name']}{'ed' if result['move2']['color'] == 'miss' else f' {t_info2} ' + str(result['move2']['dmg']) if 'dmg_str2' not in result else result['dmg_str2']} (__{result['move2']['percent']}%__)"

            s1 = f"**{z1['name2']}**\t({', '.join([config.TYPE_MAPPING[i] for i in z1_type])})\t{' used' if result['move1']['color'] != 'miss' else ''} " \
                 f"{config.COLOR_MAPPING[result['move1']['color']]}  {dmg1_str}\n"
            s2 = f"**{z2['name2']}**\t({', '.join([config.TYPE_MAPPING[i] for i in z2_type])})\t{' used' if result['move2']['color'] != 'miss' else ''} " \
                 f"{config.COLOR_MAPPING[result['move2']['color']]}  {dmg2_str}\n"

            atk_msg = apply_reroll_to_msg(is_reroll, result, s1, s2, move1_cached, move2_cached)

            await send_message(msg_hook, hidden, embeds=[], files=[], content=atk_msg)
            pre_text = (f"{result['eq1_msg']}\n" if 'eq1_name' in result else '') + (
                f"{result['eq2_msg']}\n" if 'eq2_name' in result else '')
            await asyncio.sleep(1)

            skip, old_status, is_reroll = await set_reroll(msg_hook, pre_text, result, is_reroll, move1_cached,
                                                           move2_cached, is_pvp=True, hidden=hidden,
                                                           pvp_fn=send_message)
            if skip:
                continue
            is_reroll = None

            for i, effect in enumerate(status_stack[0].copy()):
                if '0 damage' in effect:
                    status_stack[0].remove(effect)
                    break
            for i, effect in enumerate(status_stack[1].copy()):
                if '0 damage' in effect:
                    status_stack[1].remove(effect)
                    break

            print(result)

            # purple attacks
            if 'status_effect' in result:
                effect = result['status_effect']
                if result['winner'] == '1':
                    if 'next' in effect:
                        if 'next attack' in effect:
                            status_stack[0].append(effect)
                            p_x = get_val(effect)
                            count_x = status_stack[0].count(effect)
                            if 'decrease' in effect:
                                new_m = f"**{z2['name2']}**'s damage is reduced by (**{p_x}**%) for the next {'' if count_x <= 1 else ('**' + str(count_x) + '** ')}{'attack' if count_x <= 1 else 'attacks'}!"
                            else:
                                new_m = f"**{z1['name2']}**'s damage is increased by (**{p_x * count_x}**%) for the next attack!"
                            await send_message(msg_hook, hidden, embeds=[], files=[],
                                               content=pre_text + new_m)
                            move_counter += 1
                            continue
                        elif '0 damage' in effect:
                            if '2' in effect:
                                status_stack[0].append(effect)
                                status_stack[0].append(effect)
                                count_x = status_stack[0].count(effect)
                                new_m = f"**{z2['name2']}**'s damage reduced to 0 for **{count_x}** {'turns' if count_x > 1 else 'turn'}!"
                                await send_message(msg_hook, hidden, embeds=[], files=[],
                                                   content=pre_text + new_m)
                            else:
                                status_stack[0].append(effect)
                                count_x = status_stack[0].count(effect)
                                new_m = f"**{z2['name2']}**'s damage reduced to 0 for **{count_x}** {'turns' if count_x > 1 else 'turn'}!"
                                await send_message(msg_hook, hidden, embeds=[], files=[],
                                                   content=pre_text + new_m)
                        move_counter += 1
                        continue
                    elif 'knock' in effect:
                        if 'against' not in effect:
                            result['winner'] = '1'
                        else:
                            if result['move2']['color'] in effect:
                                result['winner'] = '1'
                            else:
                                new_m = f"{result['move1']['name']} was ineffective! Draw!"
                                await send_message(msg_hook, hidden, embeds=[], files=[],
                                                   content=pre_text + new_m)
                                move_counter += 1
                                continue
                    elif 'reduce' in effect and 'star' in effect:
                        status_stack[0].append(effect)
                        new_m = f"reduced {z2['name2']}'s Purple stars to 0 for the rest of the combat!"
                        await send_message(msg_hook, hidden, embeds=[], files=[],
                                           content=pre_text + new_m)
                        move_counter += 1
                        continue
                    else:
                        if effect == '@sc':
                            new_m = result['move1']['msg']
                        else:
                            new_m = result['move1']['msg'][:-1]
                            i = int(result['move1']['msg'][-1])

                            new_m = new_m.replace(config.COLOR_MAPPING[z1_moves[i]['color']], '').replace(
                                config.COLOR_MAPPING[z2_moves[i]['color']], '')
                            new_m = new_m.replace("@me",
                                                  ' ' + z1['name2'] + '\'s ' + z1_moves[i]['name'] + '  ').replace(
                                "@op", ' ' + z2['name2'] + '\'s ' + z2_moves[i]['name'] + '  ')
                            new_m += f" ({str(z1_moves[i]['dmg']) + 'dmg, ' if 'dmg' in z1_moves[i] and z1_moves[i]['dmg'] != '' else ''}{(str(round(float(p2[i]))) if p2[i] is not None else 0) if 'opposing' in result['status_effect'] else (str(round(float(p1[i]))) if p1[i] is not None else 0)}%)"
                        await send_message(msg_hook, hidden, embeds=[], files=[],
                                           content=pre_text + new_m)
                        move_counter += 1
                        if effect != '@sc':
                            continue
                elif result['winner'] == '2':
                    if 'next' in effect:
                        if 'next attack' in effect:
                            status_stack[1].append(effect)
                            p_x = get_val(effect)
                            count_x = status_stack[1].count(effect)
                            if 'decrease' in effect:
                                new_m = f"**{z1['name2']}**'s damage is reduced by (**{p_x}**%) for the next {'' if count_x <= 1 else ('**' + str(count_x) + '** ')}{'attack' if count_x <= 1 else 'attacks'}!"
                            else:
                                new_m = f"**{z2['name2']}**'s damage is increased by (**{p_x * count_x}**%) for the next attack!"
                            await send_message(msg_hook, hidden, embeds=[], files=[],
                                               content=pre_text + new_m)
                            move_counter += 1
                            continue
                        elif '0 damage' in effect:
                            if '2' in effect:
                                status_stack[1].append(effect)
                                status_stack[1].append(effect)
                                count_x = status_stack[1].count(effect)
                                new_m = f"**{z1['name2']}**'s damage reduced to 0 for **{count_x}** {'turns' if count_x > 1 else 'turn'}!"
                                await send_message(msg_hook, hidden, embeds=[], files=[],
                                                   content=pre_text + new_m)
                            else:
                                status_stack[1].append(effect)
                                count_x = status_stack[1].count(effect)
                                new_m = f"**{z1['name2']}**'s damage reduced to 0 for **{count_x}** {'turns' if count_x > 1 else 'turn'}!"
                                await send_message(msg_hook, hidden, embeds=[], files=[],
                                                   content=pre_text + new_m)
                        move_counter += 1
                        continue
                    elif 'knock' in effect:
                        if 'against' not in effect:
                            result['winner'] = '2'
                        else:
                            if result['move1']['color'] in effect:
                                result['winner'] = '2'
                            else:
                                new_m = f"{result['move2']['name']} was ineffective! Draw!"
                                await send_message(msg_hook, hidden, embeds=[], files=[],
                                                   content=pre_text + new_m)
                                move_counter += 1
                                continue
                    elif 'reduce' in effect and 'star' in effect:
                        status_stack[1].append(effect)
                        new_m = f"reduced {z1['name2']}'s Purple stars to 0 for the rest of the combat!"
                        await send_message(msg_hook, hidden, embeds=[], files=[],
                                           content=pre_text + new_m)
                        move_counter += 1
                        continue
                    else:
                        if effect == '@sc':
                            new_m = result['move2']['msg']
                        else:
                            new_m = result['move2']['msg'][:-1]
                            i = int(result['move2']['msg'][-1])

                            new_m = new_m.replace(config.COLOR_MAPPING[z1_moves[i]['color']], '').replace(
                                config.COLOR_MAPPING[z2_moves[i]['color']], '')
                            new_m = new_m.replace("@me",
                                                  ' ' + z2['name2'] + '\'s ' + z2_moves[i]['name'] + '  ').replace(
                                "@op", ' ' + z1['name2'] + '\'s ' + z1_moves[i]['name'] + '  ')
                            new_m += f" ({str(z2_moves[i]['dmg']) + 'dmg, ' if 'dmg' in z2_moves[i] and z2_moves[i]['dmg'] != '' else ''}{(str(round(float(p1[i]))) if p1[i] is not None else 0) if 'opposing' in result['status_effect'] else (str(round(float(p2[i]))) if p2[i] is not None else 0)}%)"

                        await send_message(msg_hook, hidden, embeds=[], files=[],
                                           content=pre_text + new_m)
                        move_counter += 1
                        if effect != '@sc':
                            continue

            # DRAW
            if result['winner'] == "":
                await send_message(msg_hook, hidden, embeds=[], files=[],
                                   content=(f"{result['eq1_msg']}\n" if 'eq1_name' in result else '') + (
                                       f"{result['eq2_msg']}\n" if 'eq2_name' in result else '') + f"**DRAW**", )
                move_counter += 1
                continue

            if result['winner'] == '1':
                await send_message(msg_hook, hidden, embeds=[], files=[],
                                   content=(f"{result['eq1_msg']}\n" if "eq1_name" in result else '') + (
                                       f"{result['eq2_msg']}\n" if "eq2_name" in result else '')
                                           + (f"{z1['name2']} **knocked out** 💀 {z2['name2']} 💀!" if '🎯' not in
                                                                                                       result['move1'][
                                                                                                           'mul'] else f"**{random.choice(config.CRIT_STATEMENTS).format(loser=z2['name2'])}")
                                   )
                eliminate = (2, z2['name'])
                status_stack[0] = [i for i in status_stack[0] if ('oppo' not in i) and ('enemy' not in i)]
                status_stack[1] = [i for i in status_stack[1] if ('oppo' in i) or ('enemy' in i)]
                await db_query.save_zerpmon_winrate(z1['name'], z2['name'])
                move_counter += 1

            elif result['winner'] == '2':
                await send_message(msg_hook, hidden, embeds=[], files=[],
                                   content=(f"{result['eq1_msg']}\n" if "eq1_name" in result else '') + (
                                       f"{result['eq2_msg']}\n" if "eq2_name" in result else '')
                                           + (f"{z2['name2']} **knocked out** 💀 {z1['name2']} 💀!" if '🎯' not in
                                                                                                       result['move2'][
                                                                                                           'mul'] else f"{random.choice(config.CRIT_STATEMENTS).format(loser=z1['name2'])}"))

                eliminate = (1, z1['name'])
                status_stack[1] = [i for i in status_stack[1] if ('oppo' not in i) and ('enemy' not in i)]
                status_stack[0] = [i for i in status_stack[0] if ('oppo' in i) or ('enemy' in i)]
                await db_query.save_zerpmon_winrate(z2['name'], z1['name'])
                move_counter += 1

        if eliminate[0] == 1:
            z1['rounds'].append(0)
            z2['rounds'].append(1)
            battle_log['teamA']['zerpmons'].append({'name': z1['name'],
                                                    'ko_move': result['move2']['name'] + ' ' + config.TYPE_MAPPING[
                                                        result['move2']['type']], 'rounds': z1['rounds'].copy()})
            user1_zerpmons = [i for i in user1_zerpmons if i['name'] != eliminate[1]]
            p2 = await remove_effects(p2, p1, eq1_list, z2=z2_obj)
            p1 = None
            p1_temp = None
        elif eliminate[0] == 2:
            z1['rounds'].append(1)
            z2['rounds'].append(0)
            battle_log['teamB']['zerpmons'].append({'name': z2['name'],
                                                    'ko_move': result['move1']['name'] + ' ' + config.TYPE_MAPPING[
                                                        result['move1']['type']], 'rounds': z2['rounds'].copy()})
            user2_zerpmons = [i for i in user2_zerpmons if i['name'] != eliminate[1]]
            p1 = await remove_effects(p1, p2, eq2_list, z1=z1_obj)
            p2 = None
            p2_temp = None
        file.close()
        for i in range(3):
            try:
                os.remove(f"{message.id}.png")
                break
            except Exception as e:
                print(f"Delete failed retrying {e}")

    if battle_instance['type'] != 'free_br':
        file2.close()
        for i in range(3):
            try:
                os.remove(f"{message.id}0.png")
                break
            except Exception as e:
                print(f"Delete failed retrying {e}")

    battle_instance['z1_name'] = z1['name']
    battle_instance['z2_name'] = z2['name']
    if len(user1_zerpmons) == 0:
        await send_message(msg_hook, hidden, embeds=[], files=[],
                           content=f"**WINNER**   👑**{battle_instance['username2']}**👑")
        battle_log['teamB']['zerpmons'].append({'name': z2['name'], 'rounds': z2['rounds']})
        await db_query.update_battle_log(_data1['discord_id'], _data2['discord_id'], _data1['username'], _data2['username'],
                                   battle_log['teamA'],
                                   battle_log['teamB'], winner=2,
                                   battle_type=battle_log['battle_type'] + f'{b_type}v{b_type}')
        await db_query.update_pvp_user_wr(_data1['discord_id'], 0,
                                    recent_deck=None if 'Ranked' not in battle_name else p1_deck, b_type=b_type)
        await db_query.update_pvp_user_wr(_data2['discord_id'], 1,
                                    recent_deck=None if 'Ranked' not in battle_name else p2_deck, b_type=b_type)
        return 2
    elif len(user2_zerpmons) == 0:
        await send_message(msg_hook, hidden, embeds=[], files=[],
                           content=f"**WINNER**   👑**{battle_instance['username1']}**👑")
        battle_log['teamA']['zerpmons'].append({'name': z1['name'], 'rounds': z1['rounds']})
        await db_query.update_battle_log(_data1['discord_id'], _data2['discord_id'], _data1['username'], _data2['username'],
                                   battle_log['teamA'],
                                   battle_log['teamB'], winner=1,
                                   battle_type=battle_log['battle_type'] + f'{b_type}v{b_type}')
        await db_query.update_pvp_user_wr(_data1['discord_id'], 1,
                                    recent_deck=None if 'Ranked' not in battle_name else p1_deck, b_type=b_type)
        await db_query.update_pvp_user_wr(_data2['discord_id'], 0,
                                    recent_deck=None if 'Ranked' not in battle_name else p2_deck, b_type=b_type)
        return 1


async def proceed_mission(interaction: nextcord.Interaction, user_id, active_zerpmon, old_num, is_reset, xp_mode=None):
    serial, z1 = active_zerpmon
    z1_obj = await db_query.get_zerpmon(z1['name'], user_id=user_id)
    z1['name2'] = z1_obj['name2']
    z1_level = z1_obj['level'] if 'level' in z1_obj else 1
    z1_moves = z1_obj['moves']

    _data1 = await db_query.get_owned(user_id)
    u_flair = f' | {_data1.get("flair", [])[0]}' if len(
        _data1.get("flair", [])) > 0 else ''
    user_mention = interaction.user.mention + u_flair

    z1_type = [i['value'] for i in z1['attributes'] if i['trait_type'] == 'Type']
    buffed_type1 = []
    has_omni_t = False
    if len(_data1['trainer_cards']) > 0:
        for key, tc1 in _data1['trainer_cards'].items():
            if tc1.get('nft_id', '') in OMNI_TRAINERS:
                has_omni_t = True
                break
            buffed_type1.extend(
                [i['value'] for i in tc1['attributes'] if i['trait_type'] == 'Affinity' or i['trait_type'] == 'Type'])

    buffed_zerp = ''
    for idx, i in enumerate(z1_type):
        if 'Dragon' in i:
            z1_type[idx] = 'Dragon'
            i = 'Dragon'
        if i in buffed_type1:
            buffed_zerp = i
        elif has_omni_t:
            buffed_zerp = i
            break
    lure = _data1.get('zerp_lure', {})
    lure_active = lure.get('expire_ts', 0) > time.time()
    z2 = await db_query.get_rand_zerpmon(level=z1_level, lure_type=lure.get('type') if lure_active else None)
    while z2['name'] == z1['name']:
        z2 = await db_query.get_rand_zerpmon(level=z1_level, lure_type=lure.get('type') if lure_active else None)
    z2_moves = z2['moves']
    z2_type = [i['value'] for i in z2['attributes'] if i['trait_type'] == 'Type']
    # Dealing with Equipment
    try:
        cur_z_index = [key for key, value in _data1['mission_deck'].items() if value == str(serial)][0]
        eq = _data1['equipment_decks']['mission_deck'][str(cur_z_index)]
        if eq is not None and eq in _data1['equipments']:
            eq = _data1['equipments'][eq]
            types1 = {}
            for m_i in range(4):
                types1[z1_obj['moves'][m_i]['type']] = 1
            eq_type = [_i['value'] for _i in eq['attributes'] if _i['trait_type'] == 'Type'][-1]
            if eq_type in list(types1.keys()) or eq_type == 'Omni':
                z1['buff_eq'] = eq['name']
    except:
        pass
    set_zerp_extra_meta([z1])
    main_embed, file, p1, p2, eq1_list, eq2_list, updated_blue_dict = await get_zerp_battle_embed(interaction, z1, z2,
                                                                                            z1_obj,
                                                                                            z2, z1_type,
                                                                                            z2_type,
                                                                                            [buffed_type1, []],
                                                                                            buffed_zerp, '',
                                                                                            _data1['bg'][0] if _data1.get('bg') else None,
                                                                                            None, None, )

    await asyncio.sleep(1)
    await interaction.send(content="\u200B", embed=main_embed, file=file, ephemeral=True)

    eliminate = ""
    status_stack = [[], []]
    # p1 = None
    # p2 = [(float(p['percent']) if p['percent'] not in ["0.00", "0", ""] else None) for p in
    #       z2['moves']]
    p1_temp = None
    p2_temp = None
    move_counter = 0
    lost = 0
    battle_log = {'teamA': {'trainer': None, 'zerpmons': []},
                  'teamB': {'trainer': None, 'zerpmons': []}, 'battle_type': 'Mission Battle'}
    is_reroll = None
    move1_cached, move2_cached = {}, {}
    while eliminate == "":
        await asyncio.sleep(2)
        result, p1, p2, status_stack, p1_temp, p2_temp = await battle_zerpmons((user_id, z1_obj), z2,
                                                                         [z1_type, z2_type],
                                                                         status_stack,
                                                                         [eq1_list, eq2_list], [z1.get('buff_eq', None),
                                                                                                z2.get('buff_eq',
                                                                                                       None)],
                                                                         p1, p2, p1_temp, p2_temp,
                                                                         mission=True, blue_dict=updated_blue_dict,
                                                                         idx1=None if is_reroll != 2 else move1_cached,
                                                                         idx2=None if is_reroll != 1 else move2_cached, )
        t_info1 = config.TYPE_MAPPING[result['move1']['type'].replace(" ", '')] + ' ' + result['move1']['mul']
        t_info2 = config.TYPE_MAPPING[result['move2']['type'].replace(" ", '')] + ' ' + result['move2']['mul']
        t_info1 = f'({t_info1})' if t_info1 not in ["", " "] else t_info1
        t_info2 = f'({t_info2})' if t_info2 not in ["", " "] else t_info2

        dmg1_str = f"{result['move1']['name']} {result['move1']['stars'] * '★'} (__{result['move1']['percent']}%__)" if \
            result['move1']['stars'] != '' \
            else f"{result['move1']['name']}{'ed' if result['move1']['color'] == 'miss' else f' {t_info1} ' + str(result['move1']['dmg']) if 'dmg_str1' not in result else result['dmg_str1']} (__{result['move1']['percent']}%__)"

        dmg2_str = f"{result['move2']['name']} {result['move2']['stars'] * '★'} (__{result['move2']['percent']}%__)" if \
            result['move2']['stars'] != '' \
            else f"{result['move2']['name']}{'ed' if result['move2']['color'] == 'miss' else f' {t_info2} ' + str(result['move2']['dmg']) if 'dmg_str2' not in result else result['dmg_str2']} (__{result['move2']['percent']}%__)"

        s1 = f"**{z1['name2']}**\t({', '.join([config.TYPE_MAPPING[i] for i in z1_type])})\t{' used' if result['move1']['color'] != 'miss' else ''} " \
             f"{config.COLOR_MAPPING[result['move1']['color']]}  {dmg1_str}\n"
        s2 = f"**{z2['name2']}**\t({', '.join([config.TYPE_MAPPING[i] for i in z2_type])})\t{' used' if result['move2']['color'] != 'miss' else ''} " \
             f"{config.COLOR_MAPPING[result['move2']['color']]}  {dmg2_str}\n"

        atk_msg = apply_reroll_to_msg(is_reroll, result, s1, s2, move1_cached, move2_cached)

        await interaction.send(content=atk_msg, ephemeral=True)

        pre_text = (f"{result['eq1_msg']}\n" if 'eq1_name' in result else '') + (
            f"{result['eq2_msg']}\n" if 'eq2_name' in result else '')
        await asyncio.sleep(1)

        skip, old_status, is_reroll = await set_reroll(interaction, pre_text, result, is_reroll, move1_cached,
                                                       move2_cached)
        if skip:
            continue
        is_reroll = None
        for i, effect in enumerate(status_stack[0].copy()):
            if '0 damage' in effect:
                status_stack[0].remove(effect)
                break
        for i, effect in enumerate(status_stack[1].copy()):
            if '0 damage' in effect:
                status_stack[1].remove(effect)
                break

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
            effect = result['status_effect']
            if result['winner'] == '1':
                if 'next' in effect:
                    if 'next attack' in effect:
                        status_stack[0].append(effect)
                        p_x = get_val(effect)
                        count_x = status_stack[0].count(effect)
                        if 'decrease' in effect:
                            new_m = f"**{z2['name2']}**'s damage is reduced by (**{p_x}**%) for the next {'' if count_x <= 1 else ('**' + str(count_x) + '** ')}{'attack' if count_x <= 1 else 'attacks'}!"
                        else:
                            new_m = f"**{z1['name2']}**'s damage is increased by (**{p_x * count_x}**%) for the next attack!"
                        await interaction.send(
                            content=pre_text + new_m, ephemeral=True)
                        move_counter += 1
                        continue
                    elif '0 damage' in effect:
                        if '2' in effect:
                            status_stack[0].append(effect)
                            status_stack[0].append(effect)
                            count_x = status_stack[0].count(effect)
                            new_m = f"**{z2['name2']}**'s damage reduced to 0 for **{count_x}** {'turns' if count_x > 1 else 'turn'}!"
                            await interaction.send(
                                content=pre_text + new_m, ephemeral=True)
                        else:
                            status_stack[0].append(effect)
                            count_x = status_stack[0].count(effect)
                            new_m = f"**{z2['name2']}**'s damage reduced to 0 for **{count_x}** {'turns' if count_x > 1 else 'turn'}!"
                            await interaction.send(
                                content=pre_text + new_m, ephemeral=True)
                    move_counter += 1
                    continue
                elif 'knock' in effect:
                    if 'against' not in effect:
                        result['winner'] = '1'
                    else:
                        if result['move2']['color'] in effect:
                            result['winner'] = '1'
                        else:
                            new_m = f"{result['move1']['name']} was ineffective! Draw!"
                            await interaction.send(
                                content=pre_text + new_m, ephemeral=True)
                            move_counter += 1
                            continue
                elif 'reduce' in effect and 'star' in effect:
                    status_stack[0].append(effect)
                    new_m = f"reduced {z2['name2']}'s Purple stars to 0 for the rest of the combat!"
                    await interaction.send(
                        content=pre_text + new_m, ephemeral=True)
                    move_counter += 1
                    continue
                else:
                    if effect == '@sc':
                        new_m = result['move1']['msg']
                    else:
                        new_m = result['move1']['msg'][:-1]
                        i = int(result['move1']['msg'][-1])

                        new_m = new_m.replace(config.COLOR_MAPPING[z1_moves[i]['color']], '').replace(
                            config.COLOR_MAPPING[z2_moves[i]['color']], '')
                        new_m = new_m.replace("@me", ' ' + z1['name2'] + '\'s ' + z1_moves[i]['name'] + '  ').replace(
                            "@op", ' ' + z2['name2'] + '\'s ' + z2_moves[i]['name'] + '  ')
                        new_m += f" ({str(z1_moves[i]['dmg']) + 'dmg, ' if 'dmg' in z1_moves[i] and z1_moves[i]['dmg'] != '' else ''}{(str(round(float(p2[i]))) if p2[i] is not None else 0) if 'opposing' in result['status_effect'] else (str(round(float(p1[i]))) if p1[i] is not None else 0)}%)"
                    await interaction.send(
                        content=pre_text + new_m, ephemeral=True)
                    move_counter += 1
                    if effect != '@sc':
                        continue
            elif result['winner'] == '2':
                if 'next' in effect:
                    if 'next attack' in effect:
                        status_stack[1].append(effect)
                        p_x = get_val(effect)
                        count_x = status_stack[1].count(effect)
                        if 'decrease' in effect:
                            new_m = f"**{z1['name2']}**'s damage is reduced by (**{p_x}**%) for the next {'' if count_x <= 1 else ('**' + str(count_x) + '** ')}{'attack' if count_x <= 1 else 'attacks'}!"
                        else:
                            new_m = f"**{z2['name2']}**'s damage is increased by (**{p_x * count_x}**%) for the next attack!"
                        await interaction.send(
                            content=pre_text + new_m, ephemeral=True)
                        move_counter += 1
                        continue
                    elif '0 damage' in effect:
                        if '2' in effect:
                            status_stack[1].append(effect)
                            status_stack[1].append(effect)
                            count_x = status_stack[1].count(effect)
                            new_m = f"**{z1['name2']}**'s damage reduced to 0 for **{count_x}** {'turns' if count_x > 1 else 'turn'}!"
                            await interaction.send(
                                content=pre_text + new_m, ephemeral=True)
                        else:
                            status_stack[1].append(effect)
                            count_x = status_stack[1].count(effect)
                            new_m = f"**{z1['name2']}**'s damage reduced to 0 for **{count_x}** {'turns' if count_x > 1 else 'turn'}!"
                            await interaction.send(
                                content=pre_text + new_m, ephemeral=True)
                    move_counter += 1
                    continue
                elif 'knock' in effect:
                    if 'against' not in effect:
                        result['winner'] = '2'
                    else:
                        if result['move1']['color'] in effect:
                            result['winner'] = '2'
                        else:
                            new_m = f"{result['move2']['name']} was ineffective! Draw!"
                            await interaction.send(
                                content=pre_text + new_m, ephemeral=True)
                            move_counter += 1
                            continue
                elif 'reduce' in effect and 'star' in effect:
                    status_stack[1].append(effect)
                    new_m = f"reduced {z1['name2']}'s Purple stars to 0 for the rest of the combat!"
                    await interaction.send(
                        content=pre_text + new_m, ephemeral=True)
                    move_counter += 1
                    continue
                else:
                    if effect == '@sc':
                        new_m = result['move2']['msg']
                    else:
                        new_m = result['move2']['msg'][:-1]
                        i = int(result['move2']['msg'][-1])

                        new_m = new_m.replace(config.COLOR_MAPPING[z1_moves[i]['color']], '').replace(
                            config.COLOR_MAPPING[z2_moves[i]['color']], '')
                        new_m = new_m.replace("@me", ' ' + z2['name2'] + '\'s ' + z2_moves[i]['name'] + '  ').replace(
                            "@op", ' ' + z1['name2'] + '\'s ' + z1_moves[i]['name'] + '  ')
                        new_m += f" ({str(z2_moves[i]['dmg']) + 'dmg, ' if 'dmg' in z2_moves[i] and z2_moves[i]['dmg'] != '' else ''}{(str(round(float(p1[i]))) if p1[i] is not None else 0) if 'opposing' in result['status_effect'] else (str(round(float(p2[i]))) if p2[i] is not None else 0)}%)"

                    await interaction.send(
                        content=pre_text + new_m, ephemeral=True)
                    move_counter += 1
                    if effect != '@sc':
                        continue

        # Check if status effect has stacked upto 3 then knock the Zerpmon

        # DRAW
        if result['winner'] == "" and lost == 0:
            await interaction.send(
                content=(f"{result['eq1_msg']}\n" if 'eq1_name' in result else '') + (
                    f"{result['eq2_msg']}\n" if 'eq2_name' in result else '') + f"**DRAW**",
                ephemeral=True)
            move_counter += 1
            continue

        stats_arr = [False, False, False, 0]
        t_matches = str(_data1.get('total_matches', 0))
        if (result['winner'] == '1' and lost == 0) or lost == 2:
            if lost == 0:
                await interaction.send(
                    content=(f"{result['eq1_msg']}\n" if "eq1_name" in result else '') + (
                        f"{result['eq2_msg']}\n" if "eq2_name" in result else '')
                            + (f"{z1['name2']} **knocked out** {z2['name2']}!" if '🎯' not in result['move1'][
                        'mul'] else f"{random.choice(config.CRIT_STATEMENTS).format(loser=z2['name2'])}"),
                    ephemeral=True)
            eliminate = (2, z2['name'])
            await asyncio.sleep(1)
            await interaction.send(
                f"**WINNER**   👑**{user_mention}**👑",
                ephemeral=True)
            if not lure_active:
                await db_query.save_zerpmon_winrate(z1['name'], z2['name'])
            await db_query.update_user_wr(user_id, 1, old_num, is_reset)
            battle_log['teamA']['zerpmons'].append(
                {'name': z1['name'], 'rounds': [1]})
            battle_log['teamB']['zerpmons'].append(
                {'name': z2['name'],
                 'ko_move': result['move1']['name'] + ' ' + config.TYPE_MAPPING[result['move1']['type']],
                 'rounds': [0]})
            await db_query.update_battle_log(interaction.user.id, None, interaction.user.name, 'Mission',
                                       battle_log['teamA'],
                                       battle_log['teamB'], winner=1, battle_type=battle_log['battle_type'])
            # await db_query.update_battle_count(user_id, old_num)
            # Reward user on a Win
            double_xp = 'double_xp' in _data1 and _data1['double_xp'] > time.time()
            responses = await xrpl_ws.reward_user(t_matches, _data1['address'], z1['name'], double_xp=double_xp,
                                                  lvl=z1_level,
                                                  xp_mode=xp_mode, ascended=z1_obj.get('ascended', False))
            stats_arr = responses[0]
            embed = CustomEmbed(title=f"🏆 Mission Victory 🏆",
                                color=0x8ef6e4)
            embed.add_field(name="XP", value=stats_arr[3], inline=True)
            private = True
            for res in responses[1:]:
                response, reward, qty, token_id = res
                if reward is None:
                    continue
                if reward == "XRP":
                    embed.add_field(name=f"{reward}" + ' Won', value=qty, inline=True)
                else:
                    embed.add_field(name=f"{reward}" + ' Won', value=qty, inline=True)
                if reward == "NFT":
                    embed.add_field(name=f"NFT", value=token_id[0], inline=True)
                    embed.description = f'🔥 🔥 Congratulations {user_mention} just caught **{token_id[0]}**!! 🔥 🔥\n@everyone'
                    embed.set_thumbnail(token_id[1])
                    private = False
                    await send_global_message(guild=interaction.guild, text=embed.description, image=token_id[1])

            await interaction.send(
                embed=embed,
                ephemeral=private)
            if responses[1][1] in ["XRP", "NFT"]:
                if not responses[1][0]:

                    await interaction.send(
                        f"**Failed**, something went wrong.",
                        ephemeral=True)
                else:
                    await interaction.send(
                        f"**Successfully** added {responses[1][1]} transaction to queue",
                        ephemeral=True)
            move_counter += 1

        elif (result['winner'] == '2' and lost == 0) or lost == 1:
            if lost == 0:
                await interaction.send(
                    content=f"{z2['name2']} **knocked out** {z1['name2']}!" if '🎯' not in result['move2'][
                        'mul'] else f"{random.choice(config.CRIT_STATEMENTS).format(loser=z1['name2'])}", ephemeral=True)
            eliminate = (1, z1['name'])
            await interaction.send(
                f"Sorry you **LOST** 💀",
                ephemeral=True)
            battle_log['teamA']['zerpmons'].append(
                {'name': z1['name'],
                 'ko_move': result['move2']['name'] + ' ' + config.TYPE_MAPPING[result['move2']['type']],
                 'rounds': [0]})
            battle_log['teamB']['zerpmons'].append(
                {'name': z2['name'], 'rounds': [1]})
            await db_query.update_battle_log(interaction.user.id, None, interaction.user.name, 'Mission',
                                       battle_log['teamA'],
                                       battle_log['teamB'], winner=2, battle_type=battle_log['battle_type'])
            z1['active_t'] = await checks.get_next_ts()
            await db_query.add_xrp_txn_log(t_matches, 'mission', _data1['address'], 0, 0,)
            await db_query.update_zerpmon_alive(z1, serial, user_id)
            await db_query.update_user_wr(user_id, 0, old_num, is_reset)
            if not lure_active:
                await db_query.save_zerpmon_winrate(z2['name'], z1['name'])
            # await db_query.update_battle_count(user_id, old_num)
            move_counter += 1

        await asyncio.sleep(1)
        file.close()
        for i in range(3):
            try:
                os.remove(f"{interaction.id}.png")
                break
            except Exception as e:
                print("Delete failed retrying: ", e)

    return eliminate[0], stats_arr


async def proceed_boss_battle(interaction: nextcord.Interaction):
    _data1 = await db_query.get_owned(interaction.user.id)
    u_flair = f' | {_data1.get("flair", [])[0]}' if len(
        _data1.get("flair", [])) > 0 else ''
    user_mention = interaction.user.mention + u_flair
    boss_info = await db_query.get_boss_stats()

    boss_hp = boss_info['boss_hp']
    dmg_done = 0
    tc2 = boss_info['boss_trainer']
    trainer_embed = CustomEmbed(title=f"World Boss Battle",
                                description=f"({user_mention} VS {tc2['name']} (**World Boss**))",
                                color=0xf23557)

    user1_zerpmons = _data1['zerpmons']
    tc1 = list(_data1['trainer_cards'].values())[0] if ('battle_deck' not in _data1) or (
            '0' in _data1['battle_deck'] and (not _data1['battle_deck']['0'].get('trainer', None))) else \
        _data1['trainer_cards'][_data1['battle_deck']['0']['trainer']]
    tc1i = tc1['image']
    buffed_type1 = [i['value'] for i in tc1['attributes'] if i['trait_type'] == 'Affinity' or i['trait_type'] == 'Type']

    user2_zerpmons = [boss_info['boss_zerpmon']]
    tc2i = tc2['image']

    path1 = f"./static/images/{tc1['name']}.png"
    path2 = f"./static/images/vs.png"
    path3 = f"./static/images/{tc2['name']}.png"

    url1 = tc1i if "https:/" in tc1i else 'https://cloudflare-ipfs.com/ipfs/' + tc1i.replace("ipfs://", "")
    trainer_embed.add_field(
        name=f"{tc1['name']} ({', '.join([i['value'] for i in tc1['attributes'] if i['trait_type'] == 'Affinity' or i['trait_type'] == 'Type' or i['trait_type'] == 'Status'])})",
        value="\u200B", inline=True)

    trainer_embed.add_field(name=f"🆚", value="\u200B", inline=True)

    url2 = tc2i if "https:/" in tc2i else 'https://cloudflare-ipfs.com/ipfs/' + tc2i.replace("ipfs://", "")
    trainer_embed.add_field(
        name=f"{tc2['name']} ({', '.join([i['value'] for i in tc2['attributes'] if i['trait_type'] == 'Affinity' or i['trait_type'] == 'Type' or i['trait_type'] == 'Status'])})",
        value="\u200B", inline=True)

    bg_img = _data1.get('bg', [])
    if not bg_img:
        bg_img = None
    else:
        bg_img = bg_img[0]
    await gen_image(str(interaction.id) + '0', url1, url2, path1, path2, path3, gym_bg=bg_img)

    file2 = nextcord.File(f"{interaction.id}0.png", filename="image0.png")
    trainer_embed.set_image(url=f'attachment://image0.png')

    low_z = len(user1_zerpmons)

    # Sanity check
    if 'battle_deck' in _data1 and (
            len(_data1['battle_deck']) == 0 or ('0' in _data1['battle_deck'] and len(_data1['battle_deck']['0']) == 0)):
        await interaction.send(content=f"**{_data1['username']}** please check your gym battle deck, it's empty.")
    # Proceed

    print("Start")
    try:
        del _data1['battle_deck']['0']['trainer']
    except:
        pass

    if 'battle_deck' not in _data1 or (
            len(_data1['battle_deck']) == 0 or ('0' in _data1['battle_deck'] and len(_data1['battle_deck']['0']) == 0)):
        user1_zerpmons = list(user1_zerpmons.values())[:low_z if len(user1_zerpmons) > low_z else len(user1_zerpmons)]
    else:
        user1_z = []
        for i in range(5):
            try:
                temp_zerp = user1_zerpmons[_data1['battle_deck']['0'][str(i)]]
                eq = _data1['equipment_decks']['battle_deck']['0'][str(i)]
                if eq is not None and eq in _data1['equipments']:
                    eq_ = _data1['equipments'][eq]
                    temp_zerp['buff_eq'], temp_zerp['eq'] = eq_['name'], eq
                user1_z.append(temp_zerp)
            except:
                pass
        user1_z.reverse()
        user1_zerpmons = user1_z if len(user1_z) <= low_z else user1_z[-low_z:]

    msg_hook = None
    status_stack = [[], []]
    p1 = None
    p2 = None
    p1_temp = None
    p2_temp = None
    rage_cnt = 0
    battle_log = {'teamA': {'trainer': tc1, 'zerpmons': []},
                  'teamB': {'trainer': {'name': tc2['name']}, 'zerpmons': []}, 'battle_type': 'World Boss Battle'}
    set_zerp_extra_meta(user1_zerpmons)
    set_zerp_extra_meta(user2_zerpmons)
    while len(user1_zerpmons) != 0 and len(user2_zerpmons) != 0:
        z1 = user1_zerpmons[-1]
        z1_obj = await db_query.get_zerpmon(z1['name'], user_id=interaction.user.id)
        z1['name2'] = z1_obj['name2']
        z1_moves = z1_obj['moves']

        z1_type = [i['value'] for i in z1['attributes'] if i['trait_type'] == 'Type']
        buffed_zerp = ''
        for idx, i in enumerate(z1_type):
            if 'Dragon' in i:
                z1_type[idx] = 'Dragon'
                i = 'Dragon'
            if i in buffed_type1:
                buffed_zerp = i
            elif tc1 and tc1.get('nft_id', '') in OMNI_TRAINERS:
                buffed_zerp = i
                break

        z2 = user2_zerpmons[-1]
        z2['name2'] = z2['name']
        z2_moves = z2['moves']
        z2_type = [i['value'] for i in z2['attributes'] if i['trait_type'] == 'Type']
        if 'buff_eq' in z1:
            eq1 = _data1['equipments'][z1['eq']]
            types1 = {}
            for m_i in range(4):
                types1[z1_obj['moves'][m_i]['type']] = 1
            eq_type = [_i['value'] for _i in eq1['attributes'] if _i['trait_type'] == 'Type'][-1]
            if eq_type not in list(types1.keys()) and eq_type != 'Omni':
                del z1['buff_eq']

        if p2 is None:
            p2 = [(float(p['percent']) if (p['percent'] not in ["0.00", "0", ""] and p['color'] != 'blue') else None)
                  for p in
                  z2['moves']]
        buffed_type2 = ['Omni']
        z2['buff_eq'] = boss_info.get('boss_eq', None)
        main_embed, file, p1, p2, eq1_list, eq2_list, updated_blue_dict = await get_zerp_battle_embed(interaction, z1, z2,
                                                                                                z1_obj,
                                                                                                z2, z1_type,
                                                                                                z2_type,
                                                                                                [buffed_type1,
                                                                                                 buffed_type2],
                                                                                                buffed_zerp,
                                                                                                '',
                                                                                                _data1.get('bg',
                                                                                                           [None])[
                                                                                                    0],
                                                                                                p1.copy() if p1 is not None else p1,
                                                                                                p2.copy() if p2 is not None else p2,
                                                                                                hp=boss_hp - dmg_done,
                                                                                                rage=rage_cnt >= 20)
        await asyncio.sleep(1)
        if msg_hook is None:
            msg_hook = interaction
            await interaction.send(content="\u200B", embeds=[trainer_embed, main_embed], files=[file2, file],
                                   ephemeral=True)
        else:
            await msg_hook.send(content="\u200B", embed=main_embed, file=file, ephemeral=True)

        eliminate = ""
        is_reroll = None
        move1_cached, move2_cached = {}, {}
        while eliminate == "":
            await asyncio.sleep(1)
            # If battle lasts long then end it
            if rage_cnt == 20:
                await msg_hook.send(content=f"**{z2['name']}** is now **enraged** 😡 !", ephemeral=True)
                p1, p2, _, __ = await apply_status_effects(p1, p2, [[], [f'Decrease Own Red by {p2[7]}%']])
            result, p1, p2, status_stack, p1_temp, p2_temp = await battle_zerpmons((interaction.user.id, z1_obj), z2,
                                                                             [z1_type, z2_type],
                                                                             status_stack,
                                                                             [eq1_list, eq2_list],
                                                                             [z1.get('buff_eq', None),
                                                                              z2.get('buff_eq', None)], p1, p2,
                                                                             p1_temp, p2_temp,
                                                                             blue_dict=updated_blue_dict,
                                                                             idx1=None if is_reroll != 2 else move1_cached,
                                                                             idx2=None if is_reroll != 1 else move2_cached,
                                                                             is_boss=True, rage=rage_cnt >= 20)

            rage_cnt += 1
            if rage_cnt > 20 and '💢' not in z2['name2']:
                z2['name2'] = '💢 ' + z2['name']
            t_info1 = config.TYPE_MAPPING[result['move1']['type'].replace(" ", '')] + ' ' + result['move1']['mul']
            t_info2 = config.TYPE_MAPPING['Omni'] + ' ' + result['move2']['mul']
            t_info1 = f'({t_info1})' if t_info1 not in ["", " "] else t_info1
            t_info2 = f'({t_info2})' if t_info2 not in ["", " "] else t_info2

            dmg1_str = f"{result['move1']['name']} {result['move1']['stars'] * '★'} (__{result['move1']['percent']}%__)" if \
                result['move1']['stars'] != '' \
                else f"{result['move1']['name']}{'ed' if result['move1']['color'] == 'miss' else f' {t_info1} ' + str(result['move1']['dmg']) if 'dmg_str1' not in result else result['dmg_str1']} (__{result['move1']['percent']}%__)"

            dmg2_str = f"{result['move2']['name']} {result['move2']['stars'] * '★'} (__{result['move2']['percent']}%__)" if \
                result['move2']['stars'] != '' \
                else f"{result['move2']['name']}{'ed' if result['move2']['color'] == 'miss' else f' {t_info2} ' + str(result['move2']['dmg']) if 'dmg_str2' not in result else result['dmg_str2']} (__{result['move2']['percent']}%__)"
            s1 = f"**{z1['name2']}**\t({', '.join([config.TYPE_MAPPING[i] for i in z1_type])})\t{' used' if result['move1']['color'] != 'miss' else ''} " \
                 f"{config.COLOR_MAPPING[result['move1']['color']]}  {dmg1_str}\n"
            s2 = f"**{z2['name2']}**\t({', '.join([config.TYPE_MAPPING[i] for i in z2_type])})\t{' used' if result['move2']['color'] != 'miss' else ''} " \
                 f"{config.COLOR_MAPPING[result['move2']['color']]}  {dmg2_str}\n"

            atk_msg = apply_reroll_to_msg(is_reroll, result, s1, s2, move1_cached, move2_cached)

            await msg_hook.send(content=atk_msg, ephemeral=True)
            await asyncio.sleep(1)
            pre_text = (f"{result['eq1_msg']}\n" if 'eq1_name' in result else '') + (
                f"{result['eq2_msg']}\n" if 'eq2_name' in result else '')

            skip, old_status, is_reroll = await set_reroll(interaction, pre_text, result, is_reroll, move1_cached,
                                                           move2_cached)
            if skip:
                continue
            is_reroll = None

            for i, effect in enumerate(status_stack[0].copy()):
                if '0 damage' in effect:
                    status_stack[0].remove(effect)
                    break
            for i, effect in enumerate(status_stack[1].copy()):
                if '0 damage' in effect:
                    status_stack[1].remove(effect)
                    break

            print(result)

            # purple attacks
            if 'status_effect' in result:
                effect = result['status_effect']
                if result['winner'] == '1':
                    if 'next' in effect:
                        if 'next attack' in effect:
                            status_stack[0].append(effect)
                            p_x = get_val(effect)
                            count_x = status_stack[0].count(effect)
                            if 'decrease' in effect:
                                new_m = f"**{z2['name2']}**'s damage is reduced by (**{p_x}**%) for the next {'' if count_x <= 1 else ('**' + str(count_x) + '** ')}{'attack' if count_x <= 1 else 'attacks'}!"
                            else:
                                new_m = f"**{z1['name2']}**'s damage is increased by (**{p_x * count_x}**%) for the next attack!"

                            await msg_hook.send(
                                content=pre_text + new_m, ephemeral=True)
                            continue
                        elif '0 damage' in effect:
                            if '2' in effect:
                                status_stack[0].append(effect)
                                status_stack[0].append(effect)
                                count_x = status_stack[0].count(effect)
                                new_m = f"**{z2['name2']}**'s damage reduced to 0 for **{count_x}** {'turns' if count_x > 1 else 'turn'}!"
                                await msg_hook.send(
                                    content=pre_text + new_m, ephemeral=True)
                            else:
                                status_stack[0].append(effect)
                                count_x = status_stack[0].count(effect)
                                new_m = f"**{z2['name2']}**'s damage reduced to 0 for **{count_x}** {'turns' if count_x > 1 else 'turn'}!"
                                await msg_hook.send(
                                    content=pre_text + new_m, ephemeral=True)
                        continue
                    elif 'knock' in effect:
                        if 'against' not in effect:
                            result['winner'] = '1'
                        else:
                            if result['move2']['color'] in effect:
                                result['winner'] = '1'
                            else:
                                new_m = f"{result['move1']['name']} was ineffective! Draw!"
                                await msg_hook.send(
                                    content=pre_text + new_m, ephemeral=True)
                                continue
                    elif 'reduce' in effect and 'star' in effect:
                        status_stack[0].append(effect)
                        new_m = f"reduced {z2['name2']}'s Purple stars to 0 for the rest of the combat!"
                        await msg_hook.send(
                            content=pre_text + new_m, ephemeral=True)
                        continue
                    else:
                        if effect == '@sc':
                            new_m = result['move1']['msg']
                        else:
                            new_m = result['move1']['msg'][:-1]
                            i = int(result['move1']['msg'][-1])

                            new_m = new_m.replace(config.COLOR_MAPPING[z1_moves[i]['color']], '').replace(
                                config.COLOR_MAPPING[z2_moves[i]['color']], '')
                            new_m = new_m.replace("@me",
                                                  ' ' + z1['name2'] + '\'s ' + z1_moves[i]['name'] + '  ').replace(
                                "@op", ' ' + z2['name2'] + '\'s ' + z2_moves[i]['name'] + '  ')
                            new_m += f" ({str(z1_moves[i]['dmg']) + 'dmg, ' if 'dmg' in z1_moves[i] and z1_moves[i]['dmg'] != '' else ''}{(str(round(float(p2[i]))) if p2[i] is not None else 0) if 'opposing' in result['status_effect'] else (str(round(float(p1[i]))) if p1[i] is not None else 0)}%)"
                        await msg_hook.send(
                            content=pre_text + new_m, ephemeral=True)
                        if effect != '@sc':
                            continue
                elif result['winner'] == '2':
                    if 'next' in effect:
                        if 'next attack' in effect:
                            status_stack[1].append(effect)
                            p_x = get_val(effect)
                            count_x = status_stack[1].count(effect)
                            if 'decrease' in effect:
                                new_m = f"**{z1['name2']}**'s damage is reduced by (**{p_x}**%) for the next {'' if count_x <= 1 else ('**' + str(count_x) + '** ')}{'attack' if count_x <= 1 else 'attacks'}!"
                            else:
                                new_m = f"**{z2['name2']}**'s damage is increased by (**{p_x * count_x}**%) for the next attack!"
                            await msg_hook.send(
                                content=pre_text + new_m, ephemeral=True)
                            continue
                        elif '0 damage' in effect:
                            if '2' in effect:
                                status_stack[1].append(effect)
                                status_stack[1].append(effect)
                                count_x = status_stack[1].count(effect)
                                new_m = f"**{z1['name2']}**'s damage reduced to 0 for **{count_x}** {'turns' if count_x > 1 else 'turn'}!"
                                await msg_hook.send(
                                    content=pre_text + new_m, ephemeral=True)
                            else:
                                status_stack[1].append(effect)
                                count_x = status_stack[1].count(effect)
                                new_m = f"**{z1['name2']}**'s damage reduced to 0 for **{count_x}** {'turns' if count_x > 1 else 'turn'}!"
                                await msg_hook.send(
                                    content=pre_text + new_m, ephemeral=True)
                        continue
                    elif 'knock' in effect:
                        if 'against' not in effect:
                            result['winner'] = '2'
                        else:
                            if result['move1']['color'] in effect:
                                result['winner'] = '2'
                            else:
                                new_m = f"{result['move2']['name']} was ineffective! Draw!"
                                await msg_hook.send(
                                    content=pre_text + new_m, ephemeral=True)
                                continue
                    elif 'reduce' in effect and 'star' in effect:
                        status_stack[1].append(effect)
                        new_m = f"reduced {z1['name2']}'s Purple stars to 0 for the rest of the combat!"
                        await msg_hook.send(
                            content=pre_text + new_m, ephemeral=True)
                        continue
                    else:
                        if effect == '@sc':
                            new_m = result['move2']['msg']
                        else:
                            new_m = result['move2']['msg'][:-1]
                            i = int(result['move2']['msg'][-1])

                            new_m = new_m.replace(config.COLOR_MAPPING[z1_moves[i]['color']], '').replace(
                                config.COLOR_MAPPING[z2_moves[i]['color']], '')
                            new_m = new_m.replace("@me",
                                                  ' ' + z2['name2'] + '\'s ' + z2_moves[i]['name'] + '  ').replace(
                                "@op", ' ' + z1['name2'] + '\'s ' + z1_moves[i]['name'] + '  ')
                            new_m += f" ({str(z2_moves[i]['dmg']) + 'dmg, ' if 'dmg' in z2_moves[i] and z2_moves[i]['dmg'] != '' else ''}{(str(round(float(p1[i]))) if p1[i] is not None else 0) if 'opposing' in result['status_effect'] else (str(round(float(p2[i]))) if p2[i] is not None else 0)}%)"

                        await msg_hook.send(
                            content=pre_text + new_m, ephemeral=True)
                        if effect != '@sc':
                            continue

            # DRAW
            if result['winner'] == "":
                await msg_hook.send(
                    content=(f"{result['eq1_msg']}\n" if 'eq1_name' in result else '') + (
                        f"{result['eq2_msg']}\n" if 'eq2_name' in result else '') + f"**DRAW**",
                    ephemeral=True)
                continue
            # {}'s "Crystal Ball" activated and nullified {} attack!
            if result['winner'] == '1':
                b_dmg = 100 if type(result['move1'].get('dmg', '')) is str else result['move1'].get('dmg')
                dmg_done += b_dmg
                await msg_hook.send(
                    content=(f"{result['eq1_msg']}\n" if "eq1_name" in result else '') + (
                        f"{result['eq2_msg']}\n" if "eq2_name" in result else '')
                            + f"{z1['name2']} 🏹  **Damage dealt** to 💀 {z2['name2']} 💀  **{b_dmg}**!\nWorld Boss HP left **`{max(0, boss_hp - dmg_done)}`**",
                    ephemeral=True)
                if boss_hp - dmg_done <= 0:
                    eliminate = (2, z2['name'])
                    status_stack[0] = [i for i in status_stack[0] if ('oppo' not in i) and ('enemy' not in i)]
                    status_stack[1] = [i for i in status_stack[1] if ('oppo' in i) or ('enemy' in i)]
                await db_query.save_zerpmon_winrate(z1['name'], z2['name'])

            elif result['winner'] == '2':
                await msg_hook.send(
                    content=(f"{result['eq1_msg']}\n" if "eq1_name" in result else '') + (
                        f"{result['eq2_msg']}\n" if "eq2_name" in result else '')
                            + (f"{z2['name']} **knocked out** 💀 {z1['name2']} 💀!" if '🎯' not in result['move2'][
                        'mul'] else f"{random.choice(config.CRIT_STATEMENTS).format(loser=z1['name2'])}"),
                    ephemeral=True)
                eliminate = (1, z1['name'])
                status_stack[1] = [i for i in status_stack[1] if ('oppo' not in i) and ('enemy' not in i)]
                status_stack[0] = [i for i in status_stack[0] if ('oppo' in i) or ('enemy' in i)]
                await db_query.save_zerpmon_winrate(z2['name'], z1['name'])

        if eliminate[0] == 1:
            z1['rounds'].append(0)
            z2['rounds'].append(1)
            battle_log['teamA']['zerpmons'].append({'name': z1['name'],
                                                    'ko_move': result['move2']['name'] + ' ' + config.TYPE_MAPPING[
                                                        result['move2']['type']], 'rounds': z1['rounds'].copy()})
            user1_zerpmons = [i for i in user1_zerpmons if i['name'] != eliminate[1]]
            p2 = await remove_effects(p2, p1, eq1_list, z2=z2)

            p1 = None
            p1_temp = None
        elif eliminate[0] == 2:
            z1['rounds'].append(1)
            z2['rounds'].append(0)
            battle_log['teamB']['zerpmons'].append({'name': z2['name'],
                                                    'ko_move': result['move1']['name'] + ' ' + config.TYPE_MAPPING[
                                                        result['move1']['type']], 'rounds': z2['rounds'].copy()})
            user2_zerpmons = [i for i in user2_zerpmons if i['name'] != eliminate[1]]
            p1 = await remove_effects(p1, p2, eq2_list, z1=z1_obj)
            p2 = None
            p2_temp = None
        file.close()
        for i in range(3):
            try:
                os.remove(f"{msg_hook.id}.png")
                break
            except Exception as e:
                print(f"Delete failed retrying {e}")

    file2.close()
    for i in range(3):
        try:
            os.remove(f"{msg_hook.id}0.png")
            break
        except Exception as e:
            print(f"Delete failed retrying {e}")

    embed = CustomEmbed(title="Match Result", colour=0xa4fbe3,
                        description=f"{user_mention} vs **{z2['name']}** **(World Boss)**")
    embed.add_field(name='\u200B', value='\u200B')
    if len(user1_zerpmons) == 0:
        embed.add_field(name='💀 LOST 💀',
                        value=user_mention,
                        inline=False)
        embed.add_field(
            name="Damage dealt 🏹",
            value=f"{dmg_done}",
            inline=False)
        t_dmg_user = _data1.get('boss_battle_stats', {}).get('weekly_dmg', 0) + dmg_done
        embed.add_field(name=f'Total damage dealt this week',
                        value=t_dmg_user,
                        inline=False)
        embed.add_field(name=f"Percentage of Boss's total health",
                        value=f"{int(t_dmg_user * 100 / boss_info['start_hp'])}%",
                        inline=False)
        embed.add_field(name=f'World Boss HP left',
                        value=boss_hp - dmg_done,
                        inline=False)
        await interaction.send(
            embeds=[embed],
            ephemeral=True)
        battle_log['teamB']['zerpmons'].append({'name': z2['name'], 'rounds': z2['rounds']})
        await db_query.update_battle_log(interaction.user.id, None, interaction.user.name, tc2['name'], battle_log['teamA'],
                                   battle_log['teamB'], winner=2, battle_type=battle_log['battle_type'])
        await db_query.set_boss_hp(_data1['discord_id'], dmg_done, boss_hp)
        # Save user's match
        await asyncio.sleep(1)
        return 2
    elif len(user2_zerpmons) == 0:
        # Add GP to user
        battle_log['teamA']['zerpmons'].append(
            {'name': z1['name'], 'rounds': z1['rounds']})
        await db_query.update_battle_log(interaction.user.id, None, interaction.user.name, tc2['name'], battle_log['teamA'],
                                   battle_log['teamB'], winner=1, battle_type=battle_log['battle_type'])

        # await db_query.add_gp(_data1['discord_id'], _data1['gym'] if 'gym' in _data1 else {}, gym_type, stage)
        embed.add_field(name='🏆 WINNER 🏆',
                        value=user_mention,
                        inline=False)
        embed.add_field(
            name="Damage dealt 🏹",
            value=f"{boss_hp}",
            inline=False)
        await interaction.send(
            embeds=[embed],
            ephemeral=True)
        reward_dict = {}
        await db_query.set_boss_hp(_data1['discord_id'], boss_hp, boss_hp)
        total_dmg = boss_info['total_weekly_dmg'] + boss_hp
        winners = await db_query.boss_reward_winners()
        for i in range(10):
            try:
                embed = CustomEmbed(title=f"🏆 World Boss Defeated! 🏆",
                                    color=0x680747)

                embed.set_image(z2['image'] if "https:/" in z2['image'] else 'https://cloudflare-ipfs.com/ipfs/' + z2[
                    'image'].replace("ipfs://", ""))
                content = f'🔥 🔥 Congratulations {user_mention} has defeated **{z2["name"]}**!! 🔥 🔥\n@everyone'
                t_reward = boss_info['reward']
                description = f"Starting to distribute **`{t_reward} ZRP` Boss reward!\n\n"
                for player in winners:
                    p_dmg = player['boss_battle_stats']['weekly_dmg']
                    if p_dmg > 0:
                        amt = round(p_dmg * t_reward / total_dmg, 2)
                        reward_dict[player['address']] = {'amt': amt, 'name': player['username']}
                        description += f"<@{player['discord_id']}\t**DMG dealt**: {p_dmg}\t**Reward**:`{amt}`\n"
                embed.description = description
                await send_global_message(guild=interaction.guild, text=content, image='', embed=embed,
                                          channel_id=config.BOSS_CHANNEL)
                break
            except:
                logging.error(f'Error while sending Boss rewards: {traceback.format_exc()}')
                await asyncio.sleep(10)
        logging.error(f'BossRewards: {reward_dict}')
        total_txn = len(reward_dict)
        success_txn = 0
        failed_str = ''
        for addr, obj in reward_dict.items():
            saved = await xrpl_ws.send_zrp(addr, obj['amt'], 'wager')
            if saved:
                success_txn += 1
            else:
                failed_str += f"\n{obj['name']}\t`{obj['amt']} ZRP` ❌"
        try:
            if success_txn == 0:
                await interaction.send(
                    f"**Failed**, something went wrong." + failed_str)
            else:
                await interaction.send(
                    f"**Successfully** sent ZRP. \n`({success_txn}/{total_txn} transactions confirmed)`" + failed_str)
        except:
            pass
        await db_query.reset_weekly_dmg()
        config.boss_active = False
        return 1


async def proceed_gym_tower_battle(interaction: nextcord.Interaction, user_doc):
    _data1 = user_doc
    user_mention = interaction.user.mention
    stage = user_doc.get('tower_level')

    gym_type = user_doc['gym_order'][stage - 1]
    leader = await db_query.get_gym_leader(gym_type)

    leader_name = config.LEADER_NAMES[gym_type]
    trainer_embed = CustomEmbed(title=f"Gym tower rush battle",
                                description=f"({user_mention} VS {leader_name} {config.TYPE_MAPPING[gym_type]})",
                                color=0xf23557)

    user1_zerpmons = _data1['zerpmons']
    battle_deck = {k: int(v) for k, v in _data1['battle_deck']['0'].items()}
    eq_deck = {k: int(v) if v else v for k, v in _data1['equipment_decks']['0'].items()}

    tc1 = _data1['trainers'][battle_deck['trainer']]
    tc1i = tc1['image']
    buffed_type1 = [tc1['type'] if 'type' in tc1 else tc1['affinity']]

    user2_zerpmons = leader['zerpmons']
    random.shuffle(user2_zerpmons)
    tc2i = leader['image']

    path1 = f"./static/images/{tc1['name']}.png"
    path2 = f"./static/images/vs.png"
    path3 = tc2i

    url1 = tc1i if "https:/" in tc1i else 'https://cloudflare-ipfs.com/ipfs/' + tc1i.replace("ipfs://", "")
    trainer_embed.add_field(
        name=f"{tc1['name']} ({buffed_type1})",
        value="\u200B", inline=True)

    trainer_embed.add_field(name=f"🆚", value="\u200B", inline=True)

    trainer_embed.add_field(
        name=f"{leader_name} (Level {stage})",
        value="\u200B", inline=True)

    await gen_image(str(interaction.id) + '0', url1, '', path1, path2, path3, leader['bg'])

    file2 = nextcord.File(f"{interaction.id}0.png", filename="image0.png")
    trainer_embed.set_image(url=f'attachment://image0.png')

    low_z = max(len(user1_zerpmons), len(user2_zerpmons))
    b_type = 5
    if b_type <= low_z:
        low_z = b_type

    del battle_deck['trainer']

    user1_z = []
    for i in range(5):
        try:
            temp_zerp = user1_zerpmons[battle_deck[str(i)]]
            eq = eq_deck[str(i)]
            if eq is not None and eq < 10:
                eq_ = _data1['equipments'][eq]
                temp_zerp['buff_eq'], temp_zerp['eq'] = eq_['name'], eq
            user1_z.append(temp_zerp)
        except:
            print(traceback.format_exc())
    user1_z.reverse()
    user1_zerpmons = user1_z if len(user1_z) <= low_z else user1_z[-low_z:]
    print(len(user1_zerpmons), len(user1_z))
    gym_eq = await db_query.get_eq_by_name(gym_type, gym=True)
    for _i, zerp in enumerate(user2_zerpmons):
        lvl_inc = 3 if stage > 2 else (stage - 1)
        user2_zerpmons[_i]['level'] = 10 * lvl_inc
        for i in range(lvl_inc):
            user2_zerpmons[_i] = await db_query.update_moves(user2_zerpmons[_i], save_z=False)
        if stage > 6:
            user2_zerpmons[_i]['buff_eq'], user2_zerpmons[_i]['eq'] = gym_eq['name'], gym_eq
        if stage > 10:
            gym_eq2 = await db_query.get_eq_by_name('Tattered Cloak')
            user2_zerpmons[_i]['buff_eq2'], user2_zerpmons[_i]['eq2'] = gym_eq2['name'], gym_eq2
        zerp['extra_dmg_p'] = config.GYM_DMG_BUFF[stage]
        zerp['extra_crit_p'] = config.GYM_CRIT_BUFF[stage]
    msg_hook = None
    status_stack = [[], []]
    p1 = None
    p2 = None
    p1_temp = None
    p2_temp = None
    # battle_log = {'teamA': {'trainer': tc1, 'zerpmons': []},
    #               'teamB': {'trainer': {'name': leader_name}, 'zerpmons': []}, 'battle_type': 'Gym Battle'}
    set_zerp_extra_meta(user1_zerpmons)
    set_zerp_extra_meta(user2_zerpmons)
    while len(user1_zerpmons) != 0 and len(user2_zerpmons) != 0:
        z1 = user1_zerpmons[-1]
        z1_obj = z1
        z1['name2'] = z1_obj['name2']
        z1_moves = z1_obj['moves']

        z1_type = [i['value'] for i in z1['attributes'] if i['trait_type'] == 'Type']
        buffed_zerp = ''
        for idx, i in enumerate(z1_type):
            if 'Dragon' in i:
                z1_type[idx] = 'Dragon'
                i = 'Dragon'
            if i in buffed_type1:
                buffed_zerp = i
            elif tc1 and tc1.get('nft_id', '') in OMNI_TRAINERS:
                buffed_zerp = i
                break

        z2 = user2_zerpmons[-1]
        z2_moves = z2['moves']
        z2_type = [i['value'] for i in z2['attributes'] if i['trait_type'] == 'Type']
        if 'buff_eq' in z1:
            eq1 = _data1['equipments'][z1['eq']]
            types1 = {}
            for m_i in range(4):
                types1[z1_obj['moves'][m_i]['type']] = 1
            eq_type = eq1['type'] if 'type' in eq1 else eq1['affinity']
            if eq_type not in list(types1.keys()) and eq_type != 'Omni':
                del z1['buff_eq']

        if p2 is None:
            p2 = [(float(p['percent']) if (p['percent'] not in ["0.00", "0", ""] and p['color'] != 'blue') else None)
                  for p in
                  z2['moves']]
        # buffed_type2 = [gym_type] if stage > 12 else []
        buffed_type2 = []
        main_embed, file, p1, p2, eq1_list, eq2_list, updated_blue_dict = await get_zerp_battle_embed(interaction, z1, z2,
                                                                                                z1_obj,
                                                                                                z2, z1_type,
                                                                                                z2_type, [buffed_type1,
                                                                                                          buffed_type2],
                                                                                                buffed_zerp,
                                                                                                # gym_type if stage > 12 else '',
                                                                                                '',
                                                                                                leader['bg'],
                                                                                                p1.copy() if p1 is not None else p1,
                                                                                                p2.copy() if p2 is not None else p2)
        await asyncio.sleep(1)
        main_embed.clear_fields()
        show_view = await get_battle_view(msg_hook, z1['name'], z2['name'], True)

        if msg_hook is None:
            msg_hook = interaction
            await interaction.send(content="\u200B", embeds=[trainer_embed, main_embed], files=[file2, file],
                                   ephemeral=True, view=show_view)
        else:
            await msg_hook.send(content="\u200B", embed=main_embed, file=file, ephemeral=True, view=show_view)

        eliminate = ""
        move_counter = 0
        is_reroll = None
        move1_cached, move2_cached = {}, {}
        while eliminate == "":
            await asyncio.sleep(1)
            # If battle lasts long then end it
            if move_counter == 20:
                r_int = random.randint(1, 2)
                rand_loser = z2['name'] if r_int == 2 else z1['name']
                await msg_hook.send(
                    content=f"Out of nowhere, a giant **meteor** lands right on top of 💀 {rand_loser} 💀!",
                    ephemeral=True)
                eliminate = (r_int, rand_loser)
                if r_int == 2:
                    p2 = None
                    status_stack[0] = [i for i in status_stack[0] if ('oppo' not in i) and ('enemy' not in i)]
                    status_stack[1] = [i for i in status_stack[1] if ('oppo' in i) or ('enemy' in i)]
                    await db_query.save_zerpmon_winrate(z1['name'], z2['name'])
                elif r_int == 1:
                    p1 = None
                    status_stack[1] = [i for i in status_stack[1] if ('oppo' not in i) and ('enemy' not in i)]
                    status_stack[0] = [i for i in status_stack[0] if ('oppo' in i) or ('enemy' in i)]
                    await db_query.save_zerpmon_winrate(z2['name'], z1['name'])
                break

            result, p1, p2, status_stack, p1_temp, p2_temp = await battle_zerpmons((interaction.user.id, z1_obj), z2,
                                                                             [z1_type, z2_type],
                                                                             status_stack,
                                                                             [eq1_list, eq2_list],
                                                                             [z1.get('buff_eq', None),
                                                                              z2.get('buff_eq', None)], p1, p2,
                                                                             p1_temp, p2_temp,
                                                                             blue_dict=updated_blue_dict,
                                                                             idx1=None if is_reroll != 2 else move1_cached,
                                                                             idx2=None if is_reroll != 1 else move2_cached)
            t_info1 = config.TYPE_MAPPING[result['move1']['type'].replace(" ", '')] + ' ' + result['move1']['mul']
            t_info2 = config.TYPE_MAPPING[result['move2']['type'].replace(" ", '')] + ' ' + result['move2']['mul']
            t_info1 = f'({t_info1})' if t_info1 not in ["", " "] else t_info1
            t_info2 = f'({t_info2})' if t_info2 not in ["", " "] else t_info2

            dmg1_str = f"{result['move1']['name']} {result['move1']['stars'] * '★'} (__{result['move1']['percent']}%__)" if \
                result['move1']['stars'] != '' \
                else f"{result['move1']['name']}{'ed' if result['move1']['color'] == 'miss' else f' {t_info1} ' + str(result['move1']['dmg']) if 'dmg_str1' not in result else result['dmg_str1']} (__{result['move1']['percent']}%__)"

            dmg2_str = f"{result['move2']['name']} {result['move2']['stars'] * '★'} (__{result['move2']['percent']}%__)" if \
                result['move2']['stars'] != '' \
                else f"{result['move2']['name']}{'ed' if result['move2']['color'] == 'miss' else f' {t_info2} ' + str(result['move2']['dmg']) if 'dmg_str2' not in result else result['dmg_str2']} (__{result['move2']['percent']}%__)"
            s1 = f"**{z1['name2']}**\t({', '.join([config.TYPE_MAPPING[i] for i in z1_type])})\t{' used' if result['move1']['color'] != 'miss' else ''} " \
                 f"{config.COLOR_MAPPING[result['move1']['color']]}  {dmg1_str}\n"
            s2 = f"**{z2['name2']}**\t({', '.join([config.TYPE_MAPPING[i] for i in z2_type])})\t{' used' if result['move2']['color'] != 'miss' else ''} " \
                 f"{config.COLOR_MAPPING[result['move2']['color']]}  {dmg2_str}\n"

            atk_msg = apply_reroll_to_msg(is_reroll, result, s1, s2, move1_cached, move2_cached)

            await msg_hook.send(content=atk_msg, ephemeral=True)
            await asyncio.sleep(1)
            pre_text = (f"{result['eq1_msg']}\n" if 'eq1_name' in result else '') + (
                f"{result['eq2_msg']}\n" if 'eq2_name' in result else '')

            skip, old_status, is_reroll = await set_reroll(msg_hook, pre_text, result, is_reroll, move1_cached,
                                                           move2_cached)
            if skip:
                continue
            is_reroll = None

            for i, effect in enumerate(status_stack[0].copy()):
                if '0 damage' in effect:
                    status_stack[0].remove(effect)
                    break
            for i, effect in enumerate(status_stack[1].copy()):
                if '0 damage' in effect:
                    status_stack[1].remove(effect)
                    break

            print(result)

            # purple attacks
            if 'status_effect' in result:
                effect = result['status_effect']
                if result['winner'] == '1':
                    if 'next' in effect:
                        if 'next attack' in effect:
                            status_stack[0].append(effect)
                            p_x = get_val(effect)
                            count_x = status_stack[0].count(effect)
                            if 'decrease' in effect:
                                new_m = f"**{z2['name2']}**'s damage is reduced by (**{p_x}**%) for the next {'' if count_x <= 1 else ('**' + str(count_x) + '** ')}{'attack' if count_x <= 1 else 'attacks'}!"
                            else:
                                new_m = f"**{z1['name2']}**'s damage is increased by (**{p_x * count_x}**%) for the next attack!"

                            await msg_hook.send(
                                content=pre_text + new_m, ephemeral=True)
                            move_counter += 1
                            continue
                        elif '0 damage' in effect:
                            if '2' in effect:
                                status_stack[0].append(effect)
                                status_stack[0].append(effect)
                                count_x = status_stack[0].count(effect)
                                new_m = f"**{z2['name2']}**'s damage reduced to 0 for **{count_x}** {'turns' if count_x > 1 else 'turn'}!"
                                await msg_hook.send(
                                    content=pre_text + new_m, ephemeral=True)
                            else:
                                status_stack[0].append(effect)
                                count_x = status_stack[0].count(effect)
                                new_m = f"**{z2['name2']}**'s damage reduced to 0 for **{count_x}** {'turns' if count_x > 1 else 'turn'}!"
                                await msg_hook.send(
                                    content=pre_text + new_m, ephemeral=True)

                        move_counter += 1
                        continue
                    elif 'knock' in effect:
                        if 'against' not in effect:
                            result['winner'] = '1'
                        else:
                            if result['move2']['color'] in effect:
                                result['winner'] = '1'
                            else:
                                new_m = f"{result['move1']['name']} was ineffective! Draw!"
                                await msg_hook.send(
                                    content=pre_text + new_m, ephemeral=True)
                                move_counter += 1
                                continue
                    elif 'reduce' in effect and 'star' in effect:
                        status_stack[0].append(effect)
                        new_m = f"reduced {z2['name2']}'s Purple stars to 0 for the rest of the combat!"
                        await msg_hook.send(
                            content=pre_text + new_m, ephemeral=True)
                        move_counter += 1
                        continue
                    else:
                        if effect == '@sc':
                            new_m = result['move1']['msg']
                        else:
                            new_m = result['move1']['msg'][:-1]
                            i = int(result['move1']['msg'][-1])

                            new_m = new_m.replace(config.COLOR_MAPPING[z1_moves[i]['color']], '').replace(
                                config.COLOR_MAPPING[z2_moves[i]['color']], '')
                            new_m = new_m.replace("@me",
                                                  ' ' + z1['name2'] + '\'s ' + z1_moves[i]['name'] + '  ').replace(
                                "@op", ' ' + z2['name2'] + '\'s ' + z2_moves[i]['name'] + '  ')
                            new_m += f" ({str(z1_moves[i]['dmg']) + 'dmg, ' if 'dmg' in z1_moves[i] and z1_moves[i]['dmg'] != '' else ''}{(str(round(float(p2[i]))) if p2[i] is not None else 0) if 'opposing' in result['status_effect'] else (str(round(float(p1[i]))) if p1[i] is not None else 0)}%)"
                        await msg_hook.send(
                            content=pre_text + new_m, ephemeral=True)
                        move_counter += 1
                        if effect != '@sc':
                            continue
                elif result['winner'] == '2':
                    if 'next' in effect:
                        if 'next attack' in effect:
                            status_stack[1].append(effect)
                            p_x = get_val(effect)
                            count_x = status_stack[1].count(effect)
                            if 'decrease' in effect:
                                new_m = f"**{z1['name2']}**'s damage is reduced by (**{p_x}**%) for the next {'' if count_x <= 1 else ('**' + str(count_x) + '** ')}{'attack' if count_x <= 1 else 'attacks'}!"
                            else:
                                new_m = f"**{z2['name2']}**'s damage is increased by (**{p_x * count_x}**%) for the next attack!"
                            await msg_hook.send(
                                content=pre_text + new_m, ephemeral=True)
                            move_counter += 1
                            continue
                        elif '0 damage' in effect:
                            if '2' in effect:
                                status_stack[1].append(effect)
                                status_stack[1].append(effect)
                                count_x = status_stack[1].count(effect)
                                new_m = f"**{z1['name2']}**'s damage reduced to 0 for **{count_x}** {'turns' if count_x > 1 else 'turn'}!"
                                await msg_hook.send(
                                    content=pre_text + new_m, ephemeral=True)
                            else:
                                status_stack[1].append(effect)
                                count_x = status_stack[1].count(effect)
                                new_m = f"**{z1['name2']}**'s damage reduced to 0 for **{count_x}** {'turns' if count_x > 1 else 'turn'}!"
                                await msg_hook.send(
                                    content=pre_text + new_m, ephemeral=True)
                        move_counter += 1
                        continue
                    elif 'knock' in effect:
                        if 'against' not in effect:
                            result['winner'] = '2'
                        else:
                            if result['move1']['color'] in effect:
                                result['winner'] = '2'
                            else:
                                new_m = f"{result['move2']['name']} was ineffective! Draw!"
                                await msg_hook.send(
                                    content=pre_text + new_m, ephemeral=True)
                                move_counter += 1
                                continue
                    elif 'reduce' in effect and 'star' in effect:
                        status_stack[1].append(effect)
                        new_m = f"reduced {z1['name2']}'s Purple stars to 0 for the rest of the combat!"
                        await msg_hook.send(
                            content=pre_text + new_m, ephemeral=True)
                        move_counter += 1
                        continue
                    else:
                        if effect == '@sc':
                            new_m = result['move2']['msg']
                        else:
                            new_m = result['move2']['msg'][:-1]
                            i = int(result['move2']['msg'][-1])

                            new_m = new_m.replace(config.COLOR_MAPPING[z1_moves[i]['color']], '').replace(
                                config.COLOR_MAPPING[z2_moves[i]['color']], '')
                            new_m = new_m.replace("@me",
                                                  ' ' + z2['name2'] + '\'s ' + z2_moves[i]['name'] + '  ').replace(
                                "@op", ' ' + z1['name2'] + '\'s ' + z1_moves[i]['name'] + '  ')
                            new_m += f" ({str(z2_moves[i]['dmg']) + 'dmg, ' if 'dmg' in z2_moves[i] and z2_moves[i]['dmg'] != '' else ''}{(str(round(float(p1[i]))) if p1[i] is not None else 0) if 'opposing' in result['status_effect'] else (str(round(float(p2[i]))) if p2[i] is not None else 0)}%)"

                        await msg_hook.send(
                            content=pre_text + new_m, ephemeral=True)
                        move_counter += 1
                        if effect != '@sc':
                            continue

            # DRAW
            if result['winner'] == "":
                await msg_hook.send(
                    content=(f"{result['eq1_msg']}\n" if 'eq1_name' in result else '') + (
                        f"{result['eq2_msg']}\n" if 'eq2_name' in result else '') + f"**DRAW**",
                    ephemeral=True)
                move_counter += 1
                continue
            # {}'s "Crystal Ball" activated and nullified {} attack!
            if result['winner'] == '1':
                await msg_hook.send(
                    content=(f"{result['eq1_msg']}\n" if "eq1_name" in result else '') + (
                        f"{result['eq2_msg']}\n" if "eq2_name" in result else '')
                            + (f"{z1['name2']} **knocked out** 💀 {z2['name2']} 💀!" if '🎯' not in result['move1'][
                        'mul'] else f"{random.choice(config.CRIT_STATEMENTS).format(loser=z2['name2'])}"),
                    ephemeral=True)
                eliminate = (2, z2['name'])
                status_stack[0] = [i for i in status_stack[0] if ('oppo' not in i) and ('enemy' not in i)]
                status_stack[1] = [i for i in status_stack[1] if ('oppo' in i) or ('enemy' in i)]
                await db_query.save_zerpmon_winrate(z1['name'], z2['name'])
                move_counter += 1

            elif result['winner'] == '2':
                await msg_hook.send(
                    content=(f"{result['eq1_msg']}\n" if "eq1_name" in result else '') + (
                        f"{result['eq2_msg']}\n" if "eq2_name" in result else '')
                            + (f"{z2['name2']} **knocked out** 💀 {z1['name2']} 💀!" if '🎯' not in result['move2'][
                        'mul'] else f"{random.choice(config.CRIT_STATEMENTS).format(loser=z1['name2'])}"),
                    ephemeral=True)
                eliminate = (1, z1['name'])
                status_stack[1] = [i for i in status_stack[1] if ('oppo' not in i) and ('enemy' not in i)]
                status_stack[0] = [i for i in status_stack[0] if ('oppo' in i) or ('enemy' in i)]
                await db_query.save_zerpmon_winrate(z2['name'], z1['name'])
                move_counter += 1

        if eliminate[0] == 1:
            # z1['rounds'].append(0)
            # z2['rounds'].append(1)
            # battle_log['teamA']['zerpmons'].append({'name': z1['name'],
            #                                         'ko_move': result['move2']['name'] + ' ' + config.TYPE_MAPPING[
            #                                             result['move2']['type']], 'rounds': z1['rounds'].copy()})
            user1_zerpmons = [i for i in user1_zerpmons if i['name'] != eliminate[1]]
            p2 = await remove_effects(p2, p1, eq1_list, z2=z2)
            p1 = None
            p1_temp = None
        elif eliminate[0] == 2:
            # z1['rounds'].append(1)
            # z2['rounds'].append(0)
            # battle_log['teamB']['zerpmons'].append({'name': z2['name'],
            #                                         'ko_move': result['move1']['name'] + ' ' + config.TYPE_MAPPING[
            #                                             result['move1']['type']], 'rounds': z2['rounds'].copy()})
            user2_zerpmons = [i for i in user2_zerpmons if i['name'] != eliminate[1]]

            p1 = await remove_effects(p1, p2, eq2_list, z1=z1_obj)
            p2 = None
            p2_temp = None
        file.close()
        for i in range(3):
            try:
                os.remove(f"{msg_hook.id}.png")
                break
            except Exception as e:
                print(f"Delete failed retrying {e}")

    file2.close()
    for i in range(3):
        try:
            os.remove(f"{msg_hook.id}0.png")
            break
        except Exception as e:
            print(f"Delete failed retrying {e}")

    if len(user1_zerpmons) == 0:

        embed = CustomEmbed(title="Match Result", colour=0xa4fbe3,
                            description=f"{user_mention} vs {leader_name} {config.TYPE_MAPPING[gym_type]}")

        embed.add_field(name='\u200B', value='\u200B')
        if stage > 5 or user_doc.get('lives', 0) <= 0:
            embed.add_field(
                name=f"TRP gained:",
                value=f"{stage - 1}",
                inline=False)

            embed.add_field(
                name=f"Reached Tower Level",
                value=f"{stage}",
                inline=False)
            zrp_price = await xrpl_functions.get_zrp_price_api()
            amt = round(config_extra.tower_reward[stage] / zrp_price, 2)
            await db_query.reset_gym_tower(_data1['discord_id'], amt, stage)
            embed.add_field(name=f"ZRP won", value=amt, inline=True)
            response = None
            if amt > 0:
                response = await xrpl_ws.send_zrp(_data1['address'], amt, 'tower', )
            await interaction.send(
                f"Sorry you **LOST** 💀 \nYou can try competing in **Gym Tower Rush** again by purchasing another ticket\n" + (f"**Failed**, something went wrong." if response == False else (f"**Successfully** sent `{amt}` ZRP" if response else "")),
                ephemeral=True, embed=embed)
        else:
            await db_query.dec_life_gym_tower(_data1['discord_id'])
            await interaction.send(
                f"Sorry you **LOST** 💀 \nYou still have got **one** attempt left, **Good luck**!",
                ephemeral=True, embed=embed)
        return 2
    elif len(user2_zerpmons) == 0:
        # battle_log['teamA']['zerpmons'].append(
        #     {'name': z1['name'], 'rounds': z1['rounds']})
        # await db_query.update_battle_log(interaction.user.id, None, interaction.user.name, leader_name, battle_log['teamA'],
        #                            battle_log['teamB'], winner=1, battle_type=battle_log['battle_type'])

        embed = CustomEmbed(title="Match Result", colour=0xa4fbe3,
                            description=f"{user_mention} vs {leader_name} {config.TYPE_MAPPING[gym_type]}")

        embed.add_field(name='\u200B', value='\u200B')
        embed.add_field(name='🏆 WINNER 🏆',
                        value=user_mention,
                        inline=False)
        embed.add_field(
            name=f"Gym tower level Up",
            value=f"{(stage + 1)%21}  ⬆",
            inline=False)
        embed.add_field(name='\u200B', value='\u200B')
        embed.add_field(name='\u200B', value='> Please use `/tower_rush battle` again to get another batch of random Zerpmon')
        await db_query.update_gym_tower(_data1['discord_id'], new_level=stage + 1)
        if stage + 1 > 20:
            zrp_price = await xrpl_functions.get_zrp_price_api()
            amt = round(config_extra.tower_reward[stage] / zrp_price, 2)
            embed.add_field(name=f"ZRP won", value=amt, inline=False)
            embed.add_field(name=f"**Congratulations** {user_mention} on clearing **Gym tower rush**!", value=amt, inline=False)
            response = None
            if amt > 0:
                response = await xrpl_ws.send_zrp(_data1['address'], amt, 'tower', )
        await msg_hook.send(f"**WINNER**   👑**{user_mention}**👑", embed=embed, ephemeral=True)

        return 1
