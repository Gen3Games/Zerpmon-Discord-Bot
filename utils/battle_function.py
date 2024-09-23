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
from utils import xrpl_ws, checks, translate, battle_funtion_ex
from utils.checks import gen_image

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


async def del_images(msg_hook, file, file2):
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


with open("./TypingMultipliers.json", 'r') as file:
    file = json.load(file)
    type_mapping = dict(file)


def check_battle_happening(channel_id):
    battles_in_channel = [i for msg, i in config.battle_dict.items() if i['channel_id'] == channel_id]
    wager_battles_in_channel = [i for msg, i in config.wager_battles.items() if i['channel_id'] == channel_id]
    free_br_channels = [i for i in config.free_br_channels if i == channel_id]

    return battles_in_channel == [] and wager_battles_in_channel == [] and free_br_channels == []


async def send_global_message(guild: nextcord.Guild, text, image, embed=None, channel_id=None):
    try:
        if channel_id is None:
            if guild.id != config.MAIN_GUILD[0]:
                guild = config_extra.MAIN_GUILD
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


async def get_zerp_battle_embed(message, z1, z2, z1_obj, z2_obj, z1_type, z2_type, buffed_types, buffed_zerp1,
                                buffed_zerp2,
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
    # print(z1, z2)
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

    url1 = zimg1 if "https:/" in zimg1 else config_extra.ipfsGateway + zimg1.replace("ipfs://", "")
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
                    move['stars'] = (move['stars'] + extra_star1)
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

    url2 = zimg2 if "https:/" in zimg2 else config_extra.ipfsGateway + zimg2.replace("ipfs://", "")
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
                    move['stars'] = (move['stars'] + extra_star2)
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


# bt = battle_zerpmons(await db_query.get_zerpmon("Fiepion"), await db_query.get_zerpmon("Elapix"), [["fire"], ["Bug", "Steel"]],
#                      [[], []], ["Dark", "Dark"], [None, None],
#                      blue_dict={'orig_b1': 0, 'orig_b2': 0, 'new_b1': 0, 'new_b2': 0})
# print(json.dumps(bt, indent=2))


async def proceed_gym_battle(interaction: nextcord.Interaction, gym_type, last_battle_t):
    updated_battle_t = await db_query.update_last_battle_t_gym(interaction.user.id, last_battle_t,
                                                               int(time.time()) - config_extra.GYM_CD + 3)
    if not updated_battle_t:
        await interaction.send(content=
                           f"Sorry you are under a cooldown\t(please wait a little more)",
                           ephemeral=True
                           )
        raise Exception(f"{interaction.user.name} in cooldown")
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
    tc1 = _data1['trainer_cards'].get(_data1['gym_deck']['0']['trainer'])
    if tc1 is None:
        await interaction.send(
            content=f"**{_data1['username']}** please check your gym deck, it doesn't have a trainer.")
        raise Exception("Trainer not present (Gym)")
    tc1i = tc1['image']
    buffed_types = get_type(tc1)

    user2_zerpmons = leader['zerpmons']
    random.shuffle(user2_zerpmons)
    tc2i = leader['image']

    path1 = f"./static/images/{tc1['name']}.png"
    path2 = f"./static/images/vs.png"
    path3 = tc2i

    url1 = tc1i if "https:/" in tc1i else config_extra.ipfsGateway + tc1i.replace("ipfs://", "")
    trainer_embed.add_field(
        name=f"{tc1['name']} ({', '.join(buffed_types)})",
        value="\u200B", inline=True)

    trainer_embed.add_field(name=f"🆚", value="\u200B", inline=True)

    trainer_embed.add_field(
        name=f"{leader_name} (Stage {stage})",
        value="\u200B", inline=True)

    low_z = max(len(user1_zerpmons), len(user2_zerpmons))
    b_type = 5
    if b_type <= low_z:
        low_z = b_type

    # Sanity check
    if len(_data1['gym_deck']['0']) == 0:
        await interaction.send(content=f"**{_data1['username']}** please check your gym deck, it's empty.")
        raise Exception("Zerpmon not present (Gym)")
    # Proceed

    print("Start")
    try:
        del _data1['gym_deck']['0']['trainer']
    except:
        pass

    user1_z = []
    for i in range(5):
        try:
            temp_zerp = user1_zerpmons[_data1['gym_deck']['0'][str(i)]]
            eq = _data1['equipment_decks']['gym_deck']['0'][str(i)]
            if eq is not None and eq in _data1['equipments']:
                eq_ = _data1['equipments'][eq]
                temp_zerp['buff_eq'], temp_zerp['eq'], temp_zerp['eq_id'] = eq_['name'], eq, eq_.get('token_id')
            user1_z.append(temp_zerp)
        except:
            pass
    # user1_z.reverse()
    user1_zerpmons = user1_z if len(user1_z) <= low_z else user1_z[-low_z:]

    gym_eq = await db_query.get_eq_by_name(gym_type, gym=True)
    gym_buff_obj = {
        'zerpmonLevel': 1,
    }
    for _i, zerp in enumerate(user2_zerpmons):
        lvl_inc = 3 if stage > 2 else (stage - 1)
        gym_buff_obj['zerpmonLevel'] = 10 * lvl_inc
        if stage > 6:
            user2_zerpmons[_i]['buff_eq'] = gym_eq['name']
        if stage > 10:
            gym_buff_obj['equipment2'] = 'Tattered Cloak'
        gym_buff_obj['dmgBuffPercent'] = config.GYM_DMG_BUFF[stage]
        gym_buff_obj['critBuffPercent'] = config.GYM_CRIT_BUFF[stage]
        gym_buff_obj['trainerBuff'] = stage > 12
    msg_hook = None

    uid = await db_query.make_battle_req(user1_zerpmons, user2_zerpmons, tc1['token_id'], None, 'gym', gym_buff_obj)
    result = {}
    for cnt in range(120):
        if config.battle_results[uid]:
            result = config.battle_results[uid]
            break
        await asyncio.sleep(0.3)
    del config.battle_results[uid]
    if result:
        # DB state changes comes first
        battle_log = {'teamA': {'trainer': {'name': tc1['name']}, 'zerpmons': result['roundStatsA']},
                      'teamB': {'trainer': {'name': leader_name}, 'zerpmons': result['roundStatsB']},
                      'battle_type': 'Gym Battle'}
        loser = 2 if result['winner'] == 'A' else 1
        total_gp = 0 if "gym" not in _data1 else _data1["gym"].get("gp", 0) + stage
        zrp_reward = 0
        trainer_rewards: db_query.AddXPTrainerResult | None = None
        xp_gain = 10 + (stage - 1) * 5
        resetTs, block_number = await db_query.get_gym_reset()
        cd_ts = int(time.time()) - (
                config_extra.GYM_ZERP_CD * (5 - len(result['playerAZerpmons']))
        )
        if loser == 1:
            await db_query.add_gp_queue(_data1, 0, block_number)
            await db_query.update_battle_log(interaction.user.id, None, interaction.user.name, leader_name,
                                             battle_log['teamA'],
                                             battle_log['teamB'], winner=2, battle_type=battle_log['battle_type'])
            # Save user's match
            # Here we'll also set the actual cooldown ts
            await db_query.update_gym_won(_data1['discord_id'], _data1.get('gym', {}), gym_type, stage, resetTs=resetTs,
                                          last_battle_ts=cd_ts,
                                          lost=True)
        elif loser == 2:
            # Add GP to user
            trainer_rewards = await db_query.add_xp_trainer(tc1['token_id'], _data1['address'], xp_gain)
            zrp_reward = await db_query.add_gp_queue(_data1, stage, block_number)
            await db_query.update_battle_log(interaction.user.id, None, interaction.user.name, leader_name,
                                             battle_log['teamA'],
                                             battle_log['teamB'], winner=1, battle_type=battle_log['battle_type'])

            await db_query.update_gym_won(_data1['discord_id'], _data1.get('gym', {}), gym_type, stage, resetTs=resetTs,
                                          last_battle_ts=cd_ts,
                                          lost=False)

        # Now send messages
        await gen_image(str(interaction.id) + '0', url1, '', path1, path2, path3, leader['bg'],
                        trainer_buffs=[result['playerATrainer'].get('buff') if result['playerATrainer'] else None,
                                       result['playerBTrainer'].get('buff') if result['playerBTrainer'] else None])

        file2 = nextcord.File(f"{interaction.id}0.png", filename="image0.png")
        trainer_embed.set_image(url=f'attachment://image0.png')

        idx1, idx2, log_idx = 0, 0, 0
        while idx1 < len(result['playerAZerpmons']) and idx2 < len(result['playerBZerpmons']):
            z1_obj, z2_obj = result['playerAZerpmons'][idx1], result['playerBZerpmons'][idx2]

            await battle_funtion_ex.generate_image_ex(interaction.id, z1_obj, z2_obj,
                                                      leader['bg'])
            main_embed, file = await battle_funtion_ex.get_zerp_battle_embed_ex(interaction,
                                                                                z1_obj,
                                                                                z2_obj,
                                                                                result['moveVariations'][idx1 + idx2],
                                                                                z1_obj['zerpmon']['trainer_buff'],
                                                                                z2_obj['zerpmon']['trainer_buff'],
                                                                                gym_buff_obj,
                                                                                result['roundLogs'][log_idx],
                                                                                None, )
            if msg_hook is None:
                msg_hook = interaction
                await interaction.send(content="\u200B", embeds=[trainer_embed, main_embed], files=[file2, file],
                                       ephemeral=True)
            else:
                await msg_hook.send(content="\u200B", embed=main_embed, file=file, ephemeral=True)
            while log_idx < len(result['roundLogs']):
                round_messages = result['roundLogs'][log_idx]
                msgs = translate.translate_message(interaction.locale.split('-')[0], round_messages['messages'])
                msg = ''
                for i in msgs:
                    msg += i + '\n'
                await interaction.send(content=msg, ephemeral=True)
                log_idx += 1
                await asyncio.sleep(0.4)
                if round_messages['KOd']:
                    if round_messages['roundResult'] == 'zerpmonAWin':
                        idx2 += 1
                    else:
                        idx1 += 1
                    break

        await del_images(msg_hook, file, file2)
        if loser == 1:
            await interaction.send(
                f"Sorry you **LOST** 💀 \nYou can try battling **{leader_name}** again tomorrow",
                ephemeral=True)
            await asyncio.sleep(0.5)
            return 2
        elif loser == 2:
            embeds = []
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
            embeds.append(embed)
            if trainer_rewards:
                embeds.append(checks.populate_trainer_lvl_up_embed(tc1, trainer_rewards, xp_gain))
            await msg_hook.send(
                f"**WINNER**   👑**{user_mention}**👑", embeds=embeds, ephemeral=True)
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
    lvls = None
    if battle_instance['type'] != 'free_br':
        trainer_embed = CustomEmbed(title=f"Trainers Battle",
                                    description=f"({battle_instance['username1']} VS {battle_instance['username2']})",
                                    color=0xf23557)
        tc1, zerpmon1 = None, None
        tc2, zerpmon2 = None, None
        if 'Battle Royale' in battle_name:
            if _data1.get('br_champion_decks') and _data1['br_champion_decks']['0']:
                br_deck = _data1['br_champion_decks']['0']
                if br_deck['zerpmon'] and br_deck['trainer']:
                    zerpmon1 = user1_zerpmons[br_deck['zerpmon']]
                    tc1 = _data1['trainer_cards'][br_deck['trainer']]
                    if br_deck['equipment']:
                        eq_ = _data1['equipments'][br_deck['equipment']]
                        zerpmon1['buff_eq'] = eq_['name']
            if _data2.get('br_champion_decks') and _data2['br_champion_decks']['0']:
                br_deck = _data2['br_champion_decks']['0']
                if br_deck['zerpmon'] and br_deck['trainer']:
                    zerpmon2 = user2_zerpmons[br_deck['zerpmon']]
                    tc2 = _data2['trainer_cards'][br_deck['trainer']]
                    if br_deck['equipment']:
                        eq_ = _data2['equipments'][br_deck['equipment']]
                        zerpmon2['buff_eq'] = eq_['name']
        if tc1 is None:
            tc1 = list(_data1['trainer_cards'].values())[0] if ('battle_deck' not in _data1) or (
                    '0' in _data1['battle_deck'] and (not _data1['battle_deck']['0'].get('trainer', None))) else \
                _data1['trainer_cards'][_data1['battle_deck']['0']['trainer']]
        tc1i = tc1['image']

        if tc2 is None:
            tc2 = list(_data2['trainer_cards'].values())[0] if ('battle_deck' not in _data2) or (
                    '0' in _data2['battle_deck'] and (not _data2['battle_deck']['0'].get('trainer', None))) else \
                _data2['trainer_cards'][_data2['battle_deck']['0']['trainer']]
        tc2i = tc2['image']

        path1 = f"./static/images/{tc1['name']}.png"
        path2 = f"./static/images/vs.png"
        path3 = f"./static/images/{tc2['name']}.png"

        url1 = tc1i if "https:/" in tc1i else config_extra.ipfsGateway + tc1i.replace("ipfs://", "")
        trainer_embed.add_field(
            name=f"{tc1['name']} ({', '.join([i['value'] for i in tc1['attributes'] if i['trait_type'] == 'Affinity' or i['trait_type'] == 'Type' or i['trait_type'] == 'Status'])})",
            value="\u200B", inline=True)

        trainer_embed.add_field(name=f"🆚", value="\u200B", inline=True)

        url2 = tc2i if "https:/" in tc2i else config_extra.ipfsGateway + tc2i.replace("ipfs://", "")
        trainer_embed.add_field(
            name=f"{tc2['name']} ({', '.join([i['value'] for i in tc2['attributes'] if i['trait_type'] == 'Affinity' or i['trait_type'] == 'Type' or i['trait_type'] == 'Status'])})",
            value="\u200B", inline=True)

        bg_img1 = _data1.get('bg', [])
        bg_img2 = _data2.get('bg', [])
        if bg_img1 and bg_img2:
            bg_img = random.choice([bg_img1[0], bg_img2[0]])
        else:
            bg_img = bg_img1[0] if bg_img1 else (bg_img2[0] if bg_img2 else None)
        if 'Ranked' in battle_name:
            bg_img = config.RANK_IMAGES[b_type]

        print('imageformed')
        low_z = max(len(user1_zerpmons), len(user2_zerpmons))
        if b_type <= low_z:
            low_z = b_type

        if zerpmon1 is None:
            # Sanity check
            if 'battle_deck' in _data1 and (
                    len(_data1['battle_deck']) == 0 or (
                    '0' in _data1['battle_deck'] and len(_data1['battle_deck']['0']) == 0)):
                await message.reply(content=f"**{_data1['username']}** please check your battle deck, it's empty.")
            try:
                del _data1['battle_deck']['0']['trainer']
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
                            temp_zerp['buff_eq'], temp_zerp['eq'], temp_zerp['eq_id'] = eq_['name'], eq, eq_.get('token_id')
                        user1_z.append(temp_zerp)
                    except:
                        # print(f'{traceback.format_exc()}')
                        pass
                user1_zerpmons = user1_z if len(user1_z) <= low_z else user1_z[:low_z]
        else:
            user1_zerpmons = [zerpmon1]

        if zerpmon2 is None:
            if 'battle_deck' in _data2 and (
                    len(_data2['battle_deck']) == 0 or (
                    '0' in _data2['battle_deck'] and len(_data2['battle_deck']['0']) == 0)):
                await message.reply(content=f"**{_data2['username']}** please check your battle deck, it's empty.")
            # Proceed

            try:
                del _data2['battle_deck']['0']['trainer']
            except:
                pass

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
                            temp_zerp2['buff_eq'], temp_zerp2['eq'], temp_zerp2['eq_id'] = eq_['name'], eq, eq_.get('token_id')
                        user2_z.append(temp_zerp2)
                    except:
                        # print(f'{traceback.format_exc()}')
                        pass
                user2_zerpmons = user2_z if len(user2_z) <= low_z else user2_z[:low_z]
        else:
            user2_zerpmons = [zerpmon2]
    else:
        tc1, tc2 = None, None
        user1_zerpmons = [user1_zerpmons[battle_instance['z1']]] if type(battle_instance['z1']) is str else [
            battle_instance['z1']]
        user2_zerpmons = [user2_zerpmons[battle_instance['z2']]] if type(battle_instance['z2']) is str else [
            battle_instance['z2']]
        bg_img = None
    msg_hook = None
    free_br = False
    if battle_instance['type'] == 'free_br':
        free_br = True
    is_br = 'Battle Royale' in battle_name

    uid = await db_query.make_battle_req(user1_zerpmons,
                                         user2_zerpmons,
                                         tc1['token_id'] if tc1 else None,
                                         tc2['token_id'] if tc2 else None,
                                         'free' if free_br else 'battle',
                                         is_br=is_br)
    result = {}
    for cnt in range(120):
        if config.battle_results[uid]:
            result = config.battle_results[uid]
            break
        await asyncio.sleep(0.3)
    del config.battle_results[uid]

    if result:
        if battle_instance['type'] != 'free_br':
            await gen_image(str(message.id) + '0', url1, url2, path1, path2, path3, gym_bg=bg_img,
                            trainer_buffs=[result['playerATrainer'].get('buff') if result['playerATrainer'] else None,
                                           result['playerBTrainer'].get('buff') if result['playerBTrainer'] else None]
                            )

            file2 = nextcord.File(f"{message.id}0.png", filename="image0.png")
            trainer_embed.set_image(url=f'attachment://image0.png')
        idx1, idx2, log_idx = 0, 0, 0
        while idx1 < len(result['playerAZerpmons']) and idx2 < len(result['playerBZerpmons']):
            z1_obj, z2_obj = result['playerAZerpmons'][idx1], result['playerBZerpmons'][idx2]

            await battle_funtion_ex.generate_image_ex(message.id, z1_obj, z2_obj,
                                                      bg_img, show_lvls=True)
            main_embed, file = await battle_funtion_ex.get_zerp_battle_embed_ex(message,
                                                                                z1_obj,
                                                                                z2_obj,
                                                                                result['moveVariations'][idx1 + idx2],
                                                                                z1_obj['zerpmon']['trainer_buff'],
                                                                                z2_obj['zerpmon']['trainer_buff'],
                                                                                {},
                                                                                result['roundLogs'][log_idx],
                                                                                None,
                                                                                )
            if msg_hook is None:
                if hidden:
                    msg_hook = message
                else:
                    msg_hook = message.channel
                if is_br:
                    main_embed.clear_fields()
                    show_view = await get_battle_view(msg_hook, z1_obj['zerpmon']['name'], z2_obj['zerpmon']['name'])
                else:
                    show_view = nextcord.ui.View()
                print(show_view)
                await send_message(msg_hook, hidden, content="\u200B",
                                   embeds=[main_embed] if free_br else [trainer_embed, main_embed],
                                   files=[file] if free_br else [file2, file], view=show_view)
            else:
                await send_message(msg_hook, hidden, content="\u200B", embeds=[main_embed], files=[file])
            while log_idx < len(result['roundLogs']):
                round_messages = result['roundLogs'][log_idx]
                msgs = translate.translate_message(message.locale.split('-')[0] if hidden else 'en',
                                                   round_messages['messages'])
                msg = ''
                for i in msgs:
                    msg += i + '\n'
                await send_message(msg_hook, hidden, content=msg, embeds=[], files=[], )
                log_idx += 1
                await asyncio.sleep(0.4)
                if round_messages['KOd']:
                    if round_messages['roundResult'] == 'zerpmonAWin':
                        idx2 += 1
                    else:
                        idx1 += 1
                    break
        battle_log = {'teamA': {'trainer': tc1, 'zerpmons': result['roundStatsA']},
                      'teamB': {'trainer': tc2, 'zerpmons': result['roundStatsB']},
                      'battle_type': battle_name}
        await db_query.save_zerpmon_winrate([*result['roundStatsA'], *result['roundStatsB']])
        loser = 2 if result['winner'] == 'A' else 1
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

        battle_instance['z1_name'] = z1_obj['zerpmon']['name']
        battle_instance['z2_name'] = z2_obj['zerpmon']['name']
        if loser == 1:
            await send_message(msg_hook, hidden, embeds=[], files=[],
                               content=f"**WINNER**   👑**{battle_instance['username2']}**👑")
            await db_query.update_battle_log(_data1['discord_id'], _data2['discord_id'], _data1['username'],
                                             _data2['username'],
                                             battle_log['teamA'],
                                             battle_log['teamB'], winner=2,
                                             battle_type=battle_log['battle_type'] + f'({b_type}v{b_type})')
            await db_query.update_pvp_user_wr(_data1['discord_id'], 0,
                                              recent_deck=None if 'Ranked' not in battle_name else p1_deck,
                                              b_type=b_type)
            await db_query.update_pvp_user_wr(_data2['discord_id'], 1,
                                              recent_deck=None if 'Ranked' not in battle_name else p2_deck,
                                              b_type=b_type)
            return 2
        elif loser == 2:
            await send_message(msg_hook, hidden, embeds=[], files=[],
                               content=f"**WINNER**   👑**{battle_instance['username1']}**👑")
            await db_query.update_battle_log(_data1['discord_id'], _data2['discord_id'], _data1['username'],
                                             _data2['username'],
                                             battle_log['teamA'],
                                             battle_log['teamB'], winner=1,
                                             battle_type=battle_log['battle_type'] + f'({b_type}v{b_type})')
            await db_query.update_pvp_user_wr(_data1['discord_id'], 1,
                                              recent_deck=None if 'Ranked' not in battle_name else p1_deck,
                                              b_type=b_type)
            await db_query.update_pvp_user_wr(_data2['discord_id'], 0,
                                              recent_deck=None if 'Ranked' not in battle_name else p2_deck,
                                              b_type=b_type)
            return 1


def get_type(doc: dict):
    if doc.get('nft_id', '') in OMNI_TRAINERS:
        return 'Omni'
    if "type" in doc:
        return doc["type"]
    elif "affinity" in doc:
        return doc["affinity"]
    elif "zerpmonType" in doc:
        return [i.title() for i in doc['zerpmonType']]
    else:
        types = []
        for val in doc.get("attributes", []):
            if val["trait_type"] in ['Type', 'Affinity']:
                types.append(val["value"])
        return types


async def proceed_mission(interaction: nextcord.Interaction, user_id, active_zerpmon, last_battle_t, is_reset, xp_mode=None):
    serial, z1 = active_zerpmon
    updated_battle_t = await db_query.update_last_battle_t(user_id, last_battle_t)
    if not updated_battle_t:
        await interaction.send(content=
                           f"Sorry you are under a cooldown\t(please wait a few more seconds)",
                           ephemeral=True
                           )
        raise Exception(f"{interaction.user.name} in cooldown")
    _data1 = await db_query.get_owned(user_id)
    u_flair = f' | {_data1.get("flair", [])[0]}' if len(
        _data1.get("flair", [])) > 0 else ''
    user_mention = interaction.user.mention + u_flair

    z1_type = get_type(z1)
    has_buff = False
    trainer = None
    print(z1_type)
    for key, tc1 in _data1['trainer_cards'].items():
        if tc1.get('nft_id', '') in OMNI_TRAINERS:
            trainer = tc1.get('token_id')
            has_buff = 'Omni'
            break
        trainer_type = get_type(tc1)
        if 'Omni' in z1_type or (len(trainer_type) > 0 and trainer_type[0] in z1_type):
            print('tbuff')
            trainer = tc1.get('token_id')
            has_buff = trainer_type[0]
            # print(trainer, trainer_type)
            break

    lure = _data1.get('zerp_lure', {})
    lure_active = lure.get('expire_ts', 0) > time.time()
    z2 = await db_query.get_rand_zerpmon(level=1, includeOmni=False,
                                         lure_type=lure.get('type') if lure_active else None)
    while z2['name'] == z1['name']:
        z2 = await db_query.get_rand_zerpmon(level=1, includeOmni=False,
                                             lure_type=lure.get('type') if lure_active else None)
    # Dealing with Equipment
    try:
        cur_z_index = [key for key, value in _data1['mission_deck'].items() if value == str(serial)][0]
        eq = _data1['equipment_decks']['mission_deck'][str(cur_z_index)]
        if eq is not None and eq in _data1['equipments']:
            eq = _data1['equipments'][eq]
            z1['buff_eq'] = eq['name']
            z1['eq_id'] =eq.get('token_id')
    except:
        pass
    bg_img = _data1.get('bg', [])

    uid = await db_query.make_battle_req([z1], [z2], trainer, None, 'mission')
    result = {}
    for cnt in range(120):
        if config.battle_results[uid]:
            result = config.battle_results[uid]
            break
        await asyncio.sleep(0.3)
    del config.battle_results[uid]
    if result:
        z1_obj, z2_obj = result['playerAZerpmons'][0], result['playerBZerpmons'][0]

        await battle_funtion_ex.generate_image_ex(interaction.id, z1_obj, z2_obj,
                                                  bg_img[0] if len(bg_img) > 0 else None)
        main_embed, file = await battle_funtion_ex.get_zerp_battle_embed_ex(interaction,
                                                                            z1_obj,
                                                                            z2_obj,
                                                                            result['moveVariations'][0],
                                                                            has_buff,
                                                                            '',
                                                                            {},
                                                                            result['roundLogs'][0],
                                                                            None, )
        await interaction.send(content="\u200B", embed=main_embed, file=file, ephemeral=True)
        for round_messages in result['roundLogs']:
            msgs = translate.translate_message(interaction.locale.split('-')[0], round_messages['messages'])
            msg = ''
            for i in msgs:
                msg += i + '\n'
            await interaction.send(content=msg, ephemeral=True)
            await asyncio.sleep(0.4)
        battle_log = {'teamA': {'trainer': None, 'zerpmons': result['roundStatsA']},
                      'teamB': {'trainer': None, 'zerpmons': result['roundStatsB']}, 'battle_type': 'Mission Battle'}
        loser = 2 if result['winner'] == 'A' else 1

        stats_arr = [False, False, False, 0]
        t_matches = str(_data1.get('total_matches', 0))
        if not lure_active:
            await db_query.save_zerpmon_winrate([*result['roundStatsA']])
        if loser == 2:
            await asyncio.sleep(0.5)
            await interaction.send(
                f"**WINNER**   👑**{user_mention}**👑",
                ephemeral=True)
            await db_query.update_user_wr(user_id, 1, int(t_matches), is_reset)
            await db_query.update_battle_log(interaction.user.id, None, interaction.user.name, 'Mission',
                                             battle_log['teamA'],
                                             battle_log['teamB'], winner=1, battle_type=battle_log['battle_type'],
                                             address1=_data1['address'])
            # await db_query.update_battle_count(user_id, old_num)
            # Reward user on a Win
            double_xp = 'double_xp' in _data1 and _data1['double_xp'] > time.time()
            responses = await xrpl_ws.reward_user(t_matches, _data1, z1['name'], double_xp=double_xp,
                                                  lvl=z1_obj['zerpmon']['level'] if z1_obj['zerpmon']['level'] else 1,
                                                  xp_mode=xp_mode, ascended=z1_obj['zerpmon'].get('ascended', False))
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

        elif loser == 1:
            await interaction.send(
                f"Sorry you **LOST** 💀",
                ephemeral=True)
            await db_query.update_battle_log(interaction.user.id, None, interaction.user.name, 'Mission',
                                             battle_log['teamA'],
                                             battle_log['teamB'], winner=2, battle_type=battle_log['battle_type'],
                                             address1=_data1['address'])
            z1['active_t'] = await checks.get_next_ts()
            await db_query.add_xrp_txn_log(t_matches, 'mission', _data1, 0, 0, )
            await db_query.update_zerpmon_alive(z1, serial, user_id)
            await db_query.update_user_wr(user_id, 0, int(t_matches), is_reset)

        await asyncio.sleep(1)
        file.close()
        for i in range(3):
            try:
                os.remove(f"{interaction.id}.png")
                break
            except Exception as e:
                print("Delete failed retrying: ", e)

        return loser, stats_arr


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
    buffed_type1 = get_type(tc1)

    user2_zerpmons = [boss_info['boss_zerpmon']]
    tc2i = tc2['image']

    path1 = f"./static/images/{tc1['name']}.png"
    path2 = f"./static/images/vs.png"
    path3 = f"./static/images/{tc2['name']}.png"

    url1 = tc1i if "https:/" in tc1i else config_extra.ipfsGateway + tc1i.replace("ipfs://", "")
    trainer_embed.add_field(
        name=f"{tc1['name']} ({', '.join([i['value'] for i in tc1['attributes'] if i['trait_type'] == 'Affinity' or i['trait_type'] == 'Type' or i['trait_type'] == 'Status'])})",
        value="\u200B", inline=True)

    trainer_embed.add_field(name=f"🆚", value="\u200B", inline=True)

    url2 = tc2i if "https:/" in tc2i else config_extra.ipfsGateway + tc2i.replace("ipfs://", "")
    trainer_embed.add_field(
        name=f"{tc2['name']} ({', '.join([i['value'] for i in tc2['attributes'] if i['trait_type'] == 'Affinity' or i['trait_type'] == 'Type' or i['trait_type'] == 'Status'])})",
        value="\u200B", inline=True)

    bg_img = _data1.get('bg', [])
    if not bg_img:
        bg_img = None
    else:
        bg_img = bg_img[0]

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
                    temp_zerp['buff_eq'], temp_zerp['eq'], temp_zerp['eq_id'] = eq_['name'], eq, eq_.get('token_id')
                user1_z.append(temp_zerp)
            except:
                pass
        # user1_z.reverse()
        user1_zerpmons = user1_z if len(user1_z) <= low_z else user1_z[-low_z:]
    user2_zerpmons[0]['buff_eq'] = boss_info.get('boss_eq', None)
    msg_hook = None
    uid = await db_query.make_battle_req(user1_zerpmons, user2_zerpmons, tc1['token_id'], tc2['token_id'], 'boss',
                                         startHp=boss_hp)
    result = {}
    for cnt in range(120):
        if config.battle_results[uid]:
            result = config.battle_results[uid]
            break
        await asyncio.sleep(0.3)
    del config.battle_results[uid]
    if result:
        await gen_image(str(interaction.id) + '0', url1, url2, path1, path2, path3, gym_bg=bg_img,
                        trainer_buffs=[result['playerATrainer'].get('buff') if result['playerATrainer'] else None,
                                       result['playerBTrainer'].get('buff') if result['playerBTrainer'] else None]
                        )

        file2 = nextcord.File(f"{interaction.id}0.png", filename="image0.png")
        trainer_embed.set_image(url=f'attachment://image0.png')
        idx1, idx2, log_idx = 0, 0, 0
        cur_hp = boss_hp
        while idx1 < len(result['playerAZerpmons']) and idx2 < len(result['playerBZerpmons']):
            z1_obj, z2_obj = result['playerAZerpmons'][idx1], result['playerBZerpmons'][idx2]

            await battle_funtion_ex.generate_image_ex(interaction.id, z1_obj, z2_obj,
                                                      bg_img)
            main_embed, file = await battle_funtion_ex.get_zerp_battle_embed_ex(interaction,
                                                                                z1_obj,
                                                                                z2_obj,
                                                                                result['moveVariations'][idx1 + idx2],
                                                                                z1_obj['zerpmon']['trainer_buff'],
                                                                                '',
                                                                                {},
                                                                                result['roundLogs'][log_idx],
                                                                                cur_hp, )
            cur_hp = boss_hp - result['dmgVariations'][idx1 + idx2]
            if msg_hook is None:
                msg_hook = interaction
                await interaction.send(content="\u200B", embeds=[trainer_embed, main_embed], files=[file2, file],
                                       ephemeral=True)
            else:
                await msg_hook.send(content="\u200B", embed=main_embed, file=file, ephemeral=True)
            while log_idx < len(result['roundLogs']):
                round_messages = result['roundLogs'][log_idx]
                msgs = translate.translate_message(interaction.locale.split('-')[0], round_messages['messages'])
                msg = ''
                for i in msgs:
                    msg += i + '\n'
                await interaction.send(content=msg, ephemeral=True)
                log_idx += 1
                await asyncio.sleep(0.4)
                if round_messages['KOd']:
                    if round_messages['roundResult'] == 'zerpmonAWin':
                        idx2 += 1
                    else:
                        idx1 += 1
                    break
        battle_log = {'teamA': {'trainer': {'name': tc1['name']}, 'zerpmons': result['roundStatsA']},
                      'teamB': {'trainer': {'name': tc2['name']}, 'zerpmons': result['roundStatsB']},
                      'battle_type': 'World Boss Battle'}
        dmg_done = result['dmgDealt']
        loser = 2 if result['winner'] == 'A' else 1
        await del_images(msg_hook, file, file2)
        z2 = user2_zerpmons[0]
        embed = CustomEmbed(title="Match Result", colour=0xa4fbe3,
                            description=f"{user_mention} vs **{z2['name']}** **(World Boss)**")
        embed.add_field(name='\u200B', value='\u200B')
        if loser == 1:
            embed.add_field(name='💀 LOST 💀',
                            value=user_mention,
                            inline=False)
            embed.add_field(
                name="Damage dealt 🏹",
                value=f"{dmg_done}",
                inline=False)
            t_dmg_user = float(_data1.get('boss_battle_stats', {}).get('weekly_dmg', 0) + dmg_done)
            embed.add_field(name=f'Total damage since last defeated World Boss',
                            value=f"{t_dmg_user:.2f}",
                            inline=False)
            embed.add_field(name=f"Percentage of Boss's total health",
                            value=f"{int(t_dmg_user * 100 / boss_info['start_hp'])}%",
                            inline=False)
            embed.add_field(name=f'World Boss HP left',
                            value=f"{(boss_hp - dmg_done):.2f}",
                            inline=False)
            await interaction.send(
                embeds=[embed],
                ephemeral=True)
            await db_query.update_battle_log(interaction.user.id, None, interaction.user.name, tc2['name'],
                                             battle_log['teamA'],
                                             battle_log['teamB'], winner=2, battle_type=battle_log['battle_type'])
            await db_query.add_boss_txn_log(f"boss-{_data1['address']}", _data1,
                                            1 if boss_hp <= dmg_done else 0, dmg_done, boss_hp)
            # Save user's match
            await asyncio.sleep(1)
            return 2
        elif loser == 2:
            await db_query.update_battle_log(interaction.user.id, None, interaction.user.name, tc2['name'],
                                             battle_log['teamA'],
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
            await db_query.add_boss_txn_log(f"boss-{_data1['address']}", _data1,
                                            1 if boss_hp <= dmg_done else 0, dmg_done, boss_hp)
            # total_dmg = boss_info['total_weekly_dmg'] + boss_hp
            # winners = await db_query.boss_reward_winners()
            # for i in range(10):
            #     try:
            #         embed = CustomEmbed(title=f"🏆 World Boss Defeated! 🏆",
            #                             color=0x680747)
            #
            #         embed.set_image(
            #             z2['image'] if "https:/" in z2['image'] else 'https://cloudflare-ipfs.com/ipfs/' + z2[
            #                 'image'].replace("ipfs://", ""))
            #         content = f'🔥 🔥 Congratulations **{z2["name"]}** has been defeated!! 🔥 🔥\n@everyone'
            #         t_reward = boss_info['reward']
            #         description = f"Starting to distribute `{t_reward} ZRP` Boss reward!\n\n"
            #         for player in winners:
            #             if len(reward_dict) >= 30:
            #                 break
            #             p_dmg = player['boss_battle_stats']['weekly_dmg']
            #             if p_dmg > 0:
            #                 amt = round(p_dmg * t_reward / total_dmg, 2)
            #                 reward_dict[player['address']] = {'amt': amt, 'name': player['username']}
            #                 description += f"<@{player['discord_id']}>\t**DMG dealt**: `{p_dmg:.2f}`\t**Reward**:`{amt:.2f}`\n"
            #         embed.description = description
            #         await send_global_message(guild=interaction.guild, text=content, image='', embed=embed,
            #                                   channel_id=config.BOSS_CHANNEL)
            #         break
            #     except:
            #         logging.error(f'Error while sending Boss rewards: {traceback.format_exc()}')
            #         await asyncio.sleep(10)
            # logging.error(f'BossRewards: {reward_dict}')
            total_txn = len(reward_dict)
            success_txn = 0
            failed_str = ''
            # for addr, obj in reward_dict.items():
            #     saved = await xrpl_ws.send_zrp(addr, obj['amt'], 'wager')
            #     if saved:
            #         success_txn += 1
            #     else:
            #         failed_str += f"\n{obj['name']}\t`{obj['amt']} ZRP` ❌"
            # try:
            #     if success_txn == 0:
            #         await interaction.send(
            #             f"**Failed**, something went wrong." + failed_str)
            #     else:
            #         await interaction.send(
            #             f"**Successfully** sent ZRP. \n`({success_txn}/{total_txn} transactions confirmed)`" + failed_str)
            # except:
            #     pass
            # await db_query.reset_weekly_dmg()
            config.boss_active = False
            return 1
    return 0


async def proceed_gym_tower_battle(interaction: nextcord.Interaction, user_doc):
    _data1 = user_doc
    user_mention = interaction.user.mention
    stage = user_doc.get('tower_level')
    free_mode = user_doc['is_free_mode']

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
    buffed_type1 = get_type(tc1)

    user2_zerpmons = leader['zerpmons']
    random.shuffle(user2_zerpmons)
    tc2i = leader['image']

    path1 = f"./static/images/{tc1['name']}.png"
    path2 = f"./static/images/vs.png"
    path3 = tc2i

    url1 = tc1i if "https:/" in tc1i else config_extra.ipfsGateway + tc1i.replace("ipfs://", "")
    trainer_embed.add_field(
        name=f"{tc1['name']} ({buffed_type1})",
        value="\u200B", inline=True)

    trainer_embed.add_field(name=f"🆚", value="\u200B", inline=True)

    trainer_embed.add_field(
        name=f"{leader_name} (Level {stage})",
        value="\u200B", inline=True)

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
    # user1_z.reverse()
    user1_zerpmons = user1_z if len(user1_z) <= low_z else user1_z[-low_z:]
    gym_eq = await db_query.get_eq_by_name(gym_type, gym=True)
    gym_buff_obj = {
        'zerpmonLevel': 1,
    }
    for _i, zerp in enumerate(user2_zerpmons):
        lvl_inc = 3 if stage > 2 else (stage - 1)
        gym_buff_obj['zerpmonLevel'] = 10 * lvl_inc
        if stage > 6:
            user2_zerpmons[_i]['buff_eq'] = gym_eq['name']
        if stage > 10:
            gym_buff_obj['equipment2'] = 'Tattered Cloak'
        gym_buff_obj['dmgBuffPercent'] = config.GYM_DMG_BUFF[stage]
        gym_buff_obj['critBuffPercent'] = config.GYM_CRIT_BUFF[stage]
        gym_buff_obj['trainerBuff'] = stage > 12
    msg_hook = None

    uid = await db_query.make_battle_req(user1_zerpmons, user2_zerpmons, tc1['nft_id'], None, 'tower', gym_buff_obj)
    result = {}
    for cnt in range(120):
        if config.battle_results[uid]:
            result = config.battle_results[uid]
            break
        await asyncio.sleep(0.3)
    del config.battle_results[uid]
    if result:
        await gen_image(str(interaction.id) + '0', url1, '', path1, path2, path3, leader['bg'],
                        trainer_buffs=[result['playerATrainer'].get('buff') if result['playerATrainer'] else None,
                                       result['playerBTrainer'].get('buff') if result['playerBTrainer'] else None]
                        )

        file2 = nextcord.File(f"{interaction.id}0.png", filename="image0.png")
        trainer_embed.set_image(url=f'attachment://image0.png')
        idx1, idx2, log_idx = 0, 0, 0
        while idx1 < len(result['playerAZerpmons']) and idx2 < len(result['playerBZerpmons']):
            z1_obj, z2_obj = result['playerAZerpmons'][idx1], result['playerBZerpmons'][idx2]

            await battle_funtion_ex.generate_image_ex(interaction.id, z1_obj, z2_obj,
                                                      leader['bg'])
            main_embed, file = await battle_funtion_ex.get_zerp_battle_embed_ex(interaction,
                                                                                z1_obj,
                                                                                z2_obj,
                                                                                result['moveVariations'][idx1 + idx2],
                                                                                z1_obj['zerpmon']['trainer_buff'],
                                                                                z2_obj['zerpmon']['trainer_buff'],
                                                                                gym_buff_obj,
                                                                                result['roundLogs'][0],
                                                                                None, )
            if msg_hook is None:
                msg_hook = interaction
                await interaction.send(content="\u200B", embeds=[trainer_embed, main_embed], files=[file2, file],
                                       ephemeral=True)
            else:
                await msg_hook.send(content="\u200B", embed=main_embed, file=file, ephemeral=True)
            while log_idx < len(result['roundLogs']):
                round_messages = result['roundLogs'][log_idx]
                msgs = translate.translate_message(interaction.locale.split('-')[0], round_messages['messages'])
                msg = ''
                for i in msgs:
                    msg += i + '\n'
                await interaction.send(content=msg, ephemeral=True)
                log_idx += 1
                await asyncio.sleep(0.4)
                if round_messages['KOd']:
                    if round_messages['roundResult'] == 'zerpmonAWin':
                        idx2 += 1
                    else:
                        idx1 += 1
                    break

        loser = 2 if result['winner'] == 'A' else 1
        await del_images(msg_hook, file, file2)

        if loser == 1:

            embed = CustomEmbed(title="Match Result", colour=0xa4fbe3,
                                description=f"{user_mention} vs {leader_name} {config.TYPE_MAPPING[gym_type]}")

            embed.add_field(name='\u200B', value='\u200B')
            if stage > 5 or user_doc.get('lives', 0) <= 0:
                embed.add_field(
                    name=f"TRP gained:",
                    value=f"0" if free_mode else f"{stage - 1}",
                    inline=False)

                embed.add_field(
                    name=f"Reached Tower Level",
                    value=f"{stage}",
                    inline=False)
                amt = 0
                if not free_mode:
                    zrp_price = await xrpl_functions.get_zrp_price_api()
                    amt = round(config_extra.tower_reward[stage] / zrp_price, 2)
                await db_query.reset_gym_tower(_data1['discord_id'], amt, stage, is_free_mode=free_mode)
                embed.add_field(name=f"ZRP won", value=amt, inline=True)
                response = None
                if amt > 0:
                    response = await db_query.add_tower_txn_to_gen_queue(_data1,
                                                                         f"tower-{_data1['address']}-{_data1.get('total_matches', 0)}",
                                                                         amt, )
                await interaction.send(
                    f"Sorry you **LOST** 💀 \nYou can try competing in **Gym Tower Rush** again by purchasing another ticket\n" + (
                        f"**Failed**, something went wrong." if response == False else (
                            f"**Successfully** sent `{amt}` ZRP" if response else "")),
                    ephemeral=True, embed=embed)
            else:
                await db_query.dec_life_gym_tower(_data1['discord_id'])
                await interaction.send(
                    f"Sorry you **LOST** 💀 \nYou still have got **one** attempt left, **Good luck**!",
                    ephemeral=True, embed=embed)
            return 2
        elif loser == 2:
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
                value=f"{(stage + 1) % 21}  ⬆",
                inline=False)
            embed.add_field(name='\u200B', value='\u200B')
            embed.add_field(name='\u200B',
                            value='> Please use `/tower_rush battle` again to get another batch of random Zerpmon')
            amt = 0
            if stage + 1 > 20:
                if not free_mode:
                    zrp_price = await xrpl_functions.get_zrp_price_api()
                    amt = round(config_extra.tower_reward[stage] / zrp_price, 2)
                embed.add_field(name=f"ZRP won", value=amt, inline=False)
                embed.add_field(name=f"**Congratulations** {user_mention} on clearing **Gym tower rush**!", value=amt,
                                inline=False)
                await db_query.update_gym_tower(_data1['discord_id'], new_level=stage + 1,
                                                zrp_earned=amt, is_free_mode=free_mode)
                if amt > 0:
                    await db_query.add_tower_txn_to_gen_queue(_data1,
                                                              f"tower-{_data1['address']}-{_data1.get('total_matches', 0)}",
                                                              amt, )
            else:
                await db_query.update_gym_tower(_data1['discord_id'], new_level=stage + 1)
            await msg_hook.send(f"**WINNER**   👑**{user_mention}**👑", embed=embed, ephemeral=True)

            return 1
