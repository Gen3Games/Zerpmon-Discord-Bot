import asyncio
import logging
import math
import random
import time
import traceback
from collections import Counter
from functools import partial
import nextcord
from nextcord import ButtonStyle
from nextcord.ui import Button, View

import config
import db_query
import xrpl_functions
import xumm_functions
from utils import checks, battle_function, statements
from utils.xrpl_ws import send_random_zerpmon, send_zrp, get_balance, send_equipment, check_eq_in_wallet, \
    send_nft_with_amt, cancel_offer, accept_nft, send_txn, send_nft, get_ws_client


class CustomEmbed(nextcord.Embed):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.set_footer(text='Zerpmon',
                        icon_url=config.ICON_URL)


button_cache = {'revive': [], 'mission': []}
SAFARI_REWARD_CHANCES = {
    "zrp": 88.2832,
    "battle_zone": 0.8667,
    "name_flair": 0.1667,
    "candy_white": 2.1667,
    "candy_gold": 2.1667,
    "candy_level_up": 0.8333,
    "equipment": 0,# 0.7000,
    "jackpot": 0.1833,
    "gym_refill": 2.6667,
    "revive_potion": 1.2667,
    "mission_refill": 1.2667,
    "zerpmon": 0.1333
}


print(sum(list(SAFARI_REWARD_CHANCES.values())))


async def wager_battle_r_callback(_i: nextcord.Interaction, amount, user_address, reward):
    await _i.response.defer(ephemeral=True)
    user_id = _i.user.id
    if user_id in config.ongoing_battles:
        await _i.edit_original_message(
            content=f"Please wait, one battle is already taking place for you.", view=View(), embeds=[]
        )
        return
    if user_id:
        await _i.edit_original_message(content="Generating transaction QR code...", view=View(), embeds=[])
        if reward == 'XRP':
            uuid, url, href = await xumm_functions.gen_txn_url(config.WAGER_ADDR, user_address,
                                                               amount * 10 ** 6)
        else:
            uuid, url, href = await xumm_functions.gen_zrp_txn_url(config.WAGER_ADDR, user_address,
                                                                   amount)
        embed = CustomEmbed(color=0x01f39d,
                            title=f"Please sign the transaction using this QR code or click here.",
                            url=href)

        embed.set_image(url=url)

        await _i.edit_original_message(content='', embed=embed)


async def purchase_callback(_i: nextcord.Interaction, amount, qty=1, double_xp=False, loan=False):
    user_owned_nfts = db_query.get_owned(_i.user.id)
    try:
        await _i.response.defer(ephemeral=True)
    except:
        pass
    # Sanity checks

    if user_owned_nfts is None:  # or (len(user_owned_nfts['zerpmons']) == 0 and not loan):
        await _i.edit_original_message(
            content="Sorry you can't make store/marketplace purchases, as you don't hold a Zerpmon NFT",
            embeds=[], view=View())
        return
    await _i.edit_original_message(
        content="Generating transaction QR code " + ('(**loan payment transaction**)' if loan else ''), embeds=[],
        view=View())
    user_id = str(_i.user.id)
    if not loan:
        if amount == config.POTION[0]:
            config.revive_potion_buyers[user_id] = qty
        elif amount == config.MISSION_REFILL[0]:
            config.mission_potion_buyers[user_id] = qty

    if double_xp or loan:
        send_amt = (amount * qty)
    else:
        send_amt = (amount * qty) if str(user_id) in config.store_24_hr_buyers else (amount * (qty - 1 / 2))
    user_address = user_owned_nfts['address']
    uuid, url, href = await xumm_functions.gen_txn_url(config.STORE_ADDR if not loan else config.LOAN_ADDR,
                                                       user_address, send_amt * 10 ** 6)
    embed = CustomEmbed(color=0x01f39d,
                        title=f"Please sign the transaction using this QR code or click here (expires <t:{int(time.time()) + 180}:R>).",
                        url=href)

    embed.set_image(url=url)

    await _i.edit_original_message(content='', embed=embed)

    for i in range(18):
        if loan:
            track_list = config.loan_payers
        else:
            track_list = config.latest_purchases
        print(track_list)
        if user_id in track_list and track_list[user_id] == send_amt:
            print('Purchased')
            del track_list[user_id]
            await _i.edit_original_message(embed=CustomEmbed(title="**Success**",
                                                             description=f'Loan payment done!' if loan else f"Bought **{qty}** {'Revive All Potion' if amount in [8.99, 4.495] else ('Double XP Potion' if amount == config.DOUBLE_XP_POTION else 'Mission Refill Potion')}",
                                                             ), content='')
            return True
        await asyncio.sleep(10)
    return False


async def show_store(interaction: nextcord.Interaction):
    user = interaction.user

    user_owned_nfts = db_query.get_owned(user.id)
    main_embed = CustomEmbed(title="Your Store Holdings", color=0xfcff82)
    # Sanity checks

    for owned_nfts in [user_owned_nfts]:
        if owned_nfts is None:
            main_embed.description = \
                f"Sorry no NFTs found for **{interaction.user.name}** or haven't yet verified your wallet"
            return main_embed
        if 'revive_potion' not in owned_nfts and 'mission_potion' not in owned_nfts:
            main_embed.description = \
                f"Sorry you don't have any Revive or Mission refill potions purchase one from `/store`"
            return main_embed

    main_embed.add_field(name="Revive All Potions: ",
                         value=f"**{0 if 'revive_potion' not in user_owned_nfts else user_owned_nfts['revive_potion']}**"
                               + '\t🍹',
                         inline=False)
    main_embed.add_field(name="Mission Refill Potions: ",
                         value=f"**{0 if 'mission_potion' not in user_owned_nfts else user_owned_nfts['mission_potion']}**"
                               + '\t🍶',
                         inline=False)
    active = 'double_xp' in user_owned_nfts and user_owned_nfts['double_xp'] > time.time()
    main_embed.add_field(name="Double XP Buff: ",
                         value=f"**{'Inactive' if not active else '🔥 Expires ' + '<t:' + str(int(user_owned_nfts['double_xp'])) + ':R> 🔥'}**"
                         ,
                         inline=False)

    try:
        user_bal = await get_balance(user_owned_nfts['address'])
        main_embed.add_field(name="Your XRP balance:",
                             value=f"**{user_bal:.2f}**",
                             inline=False)
    except:
        pass
    main_embed.set_footer(text=f"Usage guide: \n"
                               f"/use revive_potion zerpmon_id\n"
                               f"/use mission_refill\n")
    return main_embed


async def store_callback(interaction: nextcord.Interaction):
    user_id = interaction.user.id
    await interaction.response.defer(ephemeral=True)
    main_embed = CustomEmbed(title="Zerpmon Store", color=0xfcff82)
    main_embed.add_field(name="**Revive All Potions**" + '\t🍹',
                         value=f"Cost: `{config.POTION[0]} XRP`" if str(user_id) in config.store_24_hr_buyers else
                         f"Cost: `{config.POTION[0] / 2:.5f} XRP` \n(🥳 Half price for first purchase every 24hr 🥳)",
                         inline=False)
    main_embed.add_field(name="**Mission Refill Potions**" + '\t🍶',
                         value=f"Cost: `{config.MISSION_REFILL[0]} XRP`" if str(
                             user_id) in config.store_24_hr_buyers else
                         f"Cost: `{config.MISSION_REFILL[0] / 2:.5f} XRP` \n(🥳 Half price for first purchase every 24hr 🥳)",
                         inline=False)
    main_embed.add_field(name="**Double XP Potions**" + '\t🍉',
                         value=f"Cost: `{config.DOUBLE_XP_POTION} XRP`",
                         inline=False)

    # main_embed.add_field(name=f"\u200B",
    #                      value="**Purchase Guide**",
    #                      inline=False)
    # main_embed.add_field(name=f"\u200B",
    #                      value=f"For getting access to one of these potions send the **exact** amount in **XRP** to "
    #                      ,
    #                      inline=False)
    # main_embed.add_field(name=f"**`{config.STORE_ADDR}`** ",
    #                      value=f"or use `/buy revive_potion`, `/buy mission_refill` to buy "
    #                            f"using earned XRP",
    #                      inline=False)
    main_embed.add_field(name=f"\u200B",
                         value=f"Items will be available within a few minutes after transaction is successful",
                         inline=False)

    main_embed.set_footer(text=f"Usage guide: \n"
                               f"/use revive_potion\n"
                               f"/use mission_refill")

    sec_embed = await show_store(interaction)

    b1 = Button(label="Buy Revive All Potion", style=ButtonStyle.blurple, row=0, emoji='🍹')
    b2 = Button(label="Buy Mission Refill Potion", style=ButtonStyle.blurple, row=0, emoji='🍶')
    b3 = Button(label="Buy Double XP Potion", style=ButtonStyle.green, row=1, emoji='🍉')
    view = View()
    view.add_item(b1)
    view.add_item(b2)
    view.add_item(b3)
    view.timeout = 120  # Set a timeout of 60 seconds for the view to automatically remove it after the time is up

    # Add the button callback to the button
    b1.callback = lambda i: purchase_callback(i, config.POTION[0])
    b2.callback = lambda i: purchase_callback(i, config.MISSION_REFILL[0])
    b3.callback = lambda i: double_xp_callback(i)
    await interaction.edit_original_message(embeds=[main_embed, sec_embed], view=view)


async def double_xp_callback(i: nextcord.Interaction):
    purchased = await purchase_callback(i, config.DOUBLE_XP_POTION, double_xp=True)
    if purchased:
        # double xp
        db_query.double_xp_24hr(i.user.id)


async def switch_mission_mode(i: nextcord.Interaction, current_mode: bool):
    res = db_query.save_mission_mode(i.user.id, not current_mode)
    if res:
        await i.send(f'Switched to {"XP mode" if not current_mode else "XRP mode"} **successfully**', ephemeral=True)
    else:
        await i.send("**Failed**")


async def button_callback(user_id, interaction: nextcord.Interaction, loser: int = None,
                          mission_zerpmon_used: bool = False):
    _user_owned_nfts = {'data': db_query.get_owned(user_id), 'user': interaction.user.name}
    old_lvl = _user_owned_nfts['data'].get('level', 1)
    u_flair = f' | {_user_owned_nfts["data"].get("flair", [])[0]}' if len(
        _user_owned_nfts["data"].get("flair", [])) > 0 else ''
    _user_owned_nfts['user'] += u_flair
    user_mention = interaction.user.mention + u_flair
    _b_num = 0 if 'battle' not in _user_owned_nfts['data'] else _user_owned_nfts['data']['battle']['num']
    if _b_num > 0:
        if _user_owned_nfts['data']['battle']['reset_t'] > time.time() and _b_num >= 10:

            _hours, _minutes, _s = await checks.get_time_left_utc()

            button = Button(label="Use Mission Refill Potion", style=ButtonStyle.green)
            view = View()
            view.add_item(button)
            view.timeout = 120

            try:
                await interaction.edit(content=
                                       f"Sorry you have reached the max **10** Missions for the day, either use a "
                                       f"Mission "
                                       f"Map refill or "
                                       f" please wait **{_hours}**h **{_minutes}**m", embeds=[],
                                       view=view
                                       )
            except:
                await interaction.send(content=
                                       f"Sorry you have reached the max **10** Missions for the day, either use a "
                                       f"Mission Map refill or "
                                       f" please wait **{_hours}**h **{_minutes}**m",
                                       view=view,
                                       ephemeral=True
                                       )
            button.callback = lambda i: use_missionP_callback(i, True)
            return
        elif _user_owned_nfts['data']['battle']['reset_t'] < time.time():
            db_query.update_battle_count(user_id, -1)
            _b_num = 0

    _active_zerpmons = [(k, i) for k, i in _user_owned_nfts['data']['zerpmons'].items()
                        if 'active_t' not in i or
                        i['active_t'] < time.time()]
    mission_deck_zerpmons = [] if 'mission_deck' not in _user_owned_nfts['data'] else \
        [_i for k, _i in sorted(_user_owned_nfts['data']['mission_deck'].items(), key=lambda x: int(x[0]))]
    alive_deck = [_i for _i in mission_deck_zerpmons if _i in [ke[0] for ke in _active_zerpmons]]

    # print(active_zerpmons[0])
    r_button = Button(label="Revive Zerpmon", style=ButtonStyle.green)
    r_view = View()
    r_view.add_item(r_button)
    r_view.timeout = 120
    r_button.callback = lambda i: use_reviveP_callback(interaction, True)
    if len(_active_zerpmons) == 0:
        await interaction.send(content=
                               f"Sorry all Zerpmon are resting, please use a **revive** potion to use them "
                               f"immediately or "
                               f"wait for their **24hr** resting period",
                               view=r_view, ephemeral=True
                               )
        return

    #  Proceed with the challenge if check success
    if loser == 1 and mission_zerpmon_used:
        _battle_z = [_active_zerpmons[0]]
    else:
        _battle_z = [] if len(alive_deck) == 0 else \
            [(k, i) for (k, i) in _active_zerpmons if k == alive_deck[0]]
    if len(_battle_z) == 0:
        next_button = Button(label="Battle with next Zerpmon", style=ButtonStyle.green)
        r_view.add_item(next_button)
        next_button.callback = lambda i: button_callback(user_id, i, 1, True)
        if len(mission_deck_zerpmons) == 0:
            r_view.remove_item(r_button)
            await interaction.send(content=
                                   f"Sorry you haven't selected Mission Zerpmon, please use `/add mission_deck`"
                                   f" to set other Zerpmon for Missions or click the button below",
                                   view=r_view, ephemeral=True
                                   )
        else:

            await interaction.send(content=
                                   f"Sorry your current Mission Zerpmon are resting, please use `/add mission_deck`"
                                   f" to set other Zerpmon for Missions or click the button below to Revive selected ones",
                                   view=r_view, ephemeral=True
                                   )
        return

    try:
        await interaction.edit(content="Mission starting, 🔍 for Opponent", view=View())
    except:
        await interaction.send(content="Mission starting, 🔍 for Opponent", ephemeral=True)

    if user_id in config.ongoing_missions:
        await interaction.send(f"Please wait, one mission is already taking place.",
                               ephemeral=True)
        return
    config.ongoing_missions.append(user_id)
    xp_mode = _user_owned_nfts['data'].get('xp_mode', None)
    try:
        loser, stats = await battle_function.proceed_mission(interaction, user_id, _battle_z[0], _b_num,
                                                             xp_mode=xp_mode)
    except Exception as e:
        logging.error(f"ERROR during mission: {e}\n{traceback.format_exc()}")
        return
    finally:
        config.ongoing_missions.remove(user_id)

    button = Button(label="Battle Again" if loser == 2 else "Battle with next Zerpmon", style=ButtonStyle.green)
    xp_button = Button(label=f"Switch to {'XRP mode' if xp_mode else 'XP mode'}", style=ButtonStyle.blurple)
    view = View()
    view.add_item(button)
    view.timeout = 120
    xp_button.callback = lambda i: switch_mission_mode(i, xp_mode)
    view.add_item(xp_button)

    button2 = Button(label="Use Mission Refill Potion", style=ButtonStyle.green)
    view2 = View()
    view2.add_item(button2)
    view2.timeout = 120
    button2.callback = lambda i: use_missionP_callback(i, True)

    _b_num += 1
    reset_str = ''
    if _b_num >= 10:
        if _user_owned_nfts['data']['battle']['reset_t'] > time.time():
            _hours, _minutes, _s = await checks.get_time_left_utc()
            reset_str = f' reset time **{_hours}**h **{_minutes}**m'

    sr, nft = _battle_z[0]
    lvl, xp, xp_req, _r, _m = db_query.get_lvl_xp(nft['name'], in_mission=True if loser == 2 else False,
                                                  double_xp=_user_owned_nfts['data'].get('double_xp', 0) > time.time())
    embed = CustomEmbed(title=f"Level Up ⬆{lvl}" if stats[1] else f"\u200B",
                        color=0xff5252,
                        )
    my_button = f"https://xrp.cafe/nft/{nft['token_id']}"
    nft_type = ', '.join([i['value'] for i in nft['attributes'] if i['trait_type'] == 'Type'])
    embed.add_field(
        name=f"**{nft['name']}** ({nft_type})",
        value=f'> Level: **{lvl}/30**\n'
              f'> XP: **{xp}/{xp_req}**\n'
              f'> [view]({my_button})', inline=False)
    if stats[1]:
        embed.add_field(name="Level Up Rewards: ",
                        value=f"\u200B"
                        ,
                        inline=False)
        embed.add_field(name="Revive All Potions: ",
                        value=f"**{_r}**"
                              + '\t🍶',
                        inline=False)
        embed.add_field(name="Mission Refill Potions: ",
                        value=f"**{_m}**"
                              + '\t🍶',
                        inline=False),
        if not stats[2]:
            embed.add_field(name="Candy Fragment: ",
                            value=f"**{1}**"
                                  + '\t🧩',
                            inline=False)
    embed.set_image(
        url=nft['image'] if "https:/" in nft['image'] else 'https://cloudflare-ipfs.com/ipfs/' + nft[
            'image'].replace("ipfs://", ""))
    description = '**XP MODE**:' + ('🟢' if xp_mode else '🔴') + '\n\n**XRP MODE**:' + (
        '🟢' if xp_mode == False else '🔴')
    await interaction.send(embeds=[embed, CustomEmbed(
        title=f'**Remaining Missions** for the day: `{10 - _b_num}`', description=description)] if loser == 2 else [
        CustomEmbed(title=f'**Remaining Missions** for the day: `{10 - _b_num}`' + reset_str, description=description)]
                           , view=view2 if (10 - _b_num == 0) else view, ephemeral=True)
    button.callback = lambda i: button_callback(user_id, i, loser, mission_zerpmon_used)


async def use_missionP_callback(interaction: nextcord.Interaction, button=False):
    user = interaction.user
    user_id = user.id
    user_owned_nfts = {'data': db_query.get_owned(user.id), 'user': user.name}

    if button:
        i_id = interaction.id
        if len(button_cache['mission']) > 300:
            button_cache['mission'] = button_cache['mission'][200:]
        if i_id in button_cache['mission']:
            return
        else:
            button_cache['mission'].append(i_id)
    # Sanity checks
    if user.id in config.ongoing_missions:
        await interaction.send(f"Please wait, potions can't be used during a Battle.",
                               ephemeral=True)
        return

    for owned_nfts in [user_owned_nfts]:
        if owned_nfts['data'] is None:
            await interaction.send(
                f"Sorry no NFTs found for **{owned_nfts['user']}** or haven't yet verified your wallet", ephemeral=True)
            return

        if 'mission_potion' not in owned_nfts['data'] or int(owned_nfts['data']['mission_potion']) <= 0:
            return (await store_callback(interaction))

    saved = db_query.mission_refill(user_id)
    if not saved:
        await interaction.send(
            f"**Failed**",
            ephemeral=True)
        return False
    else:
        button = Button(label="Start Mission", style=ButtonStyle.green)
        view = View()
        view.add_item(button)
        view.timeout = 60
        button.callback = lambda i: button_callback(interaction.user.id, i, )
        await interaction.send("**SUCCESS**", view=view, ephemeral=True)
        return True


async def use_reviveP_callback(interaction: nextcord.Interaction, button=False):
    user = interaction.user

    user_owned_nfts = {'data': db_query.get_owned(user.id), 'user': user.name}

    if button:
        i_id = interaction.id
        if len(button_cache['revive']) > 300:
            button_cache['revive'] = button_cache['revive'][200:]
        if i_id in button_cache['revive']:
            return
        else:
            button_cache['revive'].append(i_id)
    # Sanity checks
    if user.id in config.ongoing_missions:
        await interaction.send(f"Please wait, potions can't be used during a Battle.",
                               ephemeral=True)
        return

    for owned_nfts in [user_owned_nfts]:
        if owned_nfts['data'] is None:
            await interaction.send(
                f"Sorry no NFTs found for **{owned_nfts['user']}** or haven't yet verified your wallet", ephemeral=True)
            return

        if len(owned_nfts['data']['zerpmons']) == 0:
            await interaction.send(
                f"Sorry **0** Zerpmon found for **{owned_nfts['user']}**, need **1** to revive",
                ephemeral=True)
            return

        if 'revive_potion' not in owned_nfts['data'] or int(owned_nfts['data']['revive_potion']) <= 0:
            # await interaction.send(
            #     f"Sorry **0** Revive All Potions found for **{owned_nfts['user']}**, need **1** to revive Zerpmon",
            #     ephemeral=True)
            return (await store_callback(interaction))

    # await interaction.send(
    #     f"**Reviving all Zerpmon...**",
    #     ephemeral=True)
    saved = db_query.revive_zerpmon(user.id)
    if not saved:
        await interaction.send(
            f"**Failed**",
            ephemeral=True)
        return False
    else:
        button = Button(label="Start Mission", style=ButtonStyle.green)
        view = View()
        view.add_item(button)
        view.timeout = 60
        button.callback = lambda i: button_callback(interaction.user.id, i, )
        await interaction.send("**SUCCESS**", view=view, ephemeral=True)
        return True


async def gym_callback(user_id, interaction: nextcord.Interaction, gym_leader):
    if user_id in config.ongoing_gym_battles:
        await interaction.send('Please wait another gym battle is already taking place!', ephemeral=True)
        return
    config.ongoing_gym_battles.append(user_id)
    try:
        await interaction.send('Battle beginning!', ephemeral=True)
        winner = await battle_function.proceed_gym_battle(interaction, gym_leader)
    except Exception as e:
        logging.error(f'ERROR in gym battle: {traceback.format_exc()}')
    finally:
        config.ongoing_gym_battles.remove(user_id)


async def show_zrp_holdings(interaction: nextcord.Interaction):
    user = interaction.user

    user_owned_nfts = db_query.get_owned(user.id)
    main_embed = CustomEmbed(title="Your ZRP Store Holdings", color=0xfcff82)
    # Sanity checks

    for owned_nfts in [user_owned_nfts]:
        if owned_nfts is None:
            main_embed.description = \
                f"Sorry no NFTs found for **{interaction.user.name}** or haven't yet verified your wallet"
            return main_embed

    main_embed.add_field(name="Zerpmon Equipment: ",
                         value=f"**{len(user_owned_nfts.get('equipments', {}))}**"
                               + '\t🗡️',
                         inline=False)
    main_embed.add_field(name="Gym Refill: ",
                         value=f"**{0 if ('gym' not in user_owned_nfts or 'refill_potion' not in user_owned_nfts['gym']) else user_owned_nfts['gym']['refill_potion']}**"
                               + '\t🍵',
                         inline=False)
    main_embed.add_field(name="Power Candy (White): ",
                         value=f"**{0 if 'white_candy' not in user_owned_nfts else user_owned_nfts['white_candy']}**"
                               + '\t🍬',
                         inline=False)
    main_embed.add_field(name="Power Candy (Gold): ",
                         value=f"**{0 if 'gold_candy' not in user_owned_nfts else user_owned_nfts['gold_candy']}**"
                               + '\t🍭',
                         inline=False)
    main_embed.add_field(name="Golden Liquorice: ",
                         value=f"**{0 if 'lvl_candy' not in user_owned_nfts else user_owned_nfts['lvl_candy']}**"
                               + '\t🍯',
                         inline=False)
    main_embed.add_field(name="Battle Zones: ",
                         value=f"**{len(user_owned_nfts.get('bg', []))}**"
                               + '\t🏟️',
                         inline=False)
    main_embed.add_field(name="Name Flair:",
                         value=f"**{len(user_owned_nfts.get('flair', []))}**"
                               + '\t💠',
                         inline=False)
    main_embed.add_field(name="Candy Fragments:",
                         value=f"**{user_owned_nfts.get('candy_frag', )}**"
                               + '\t🧩',
                         inline=False)
    j_bal = float(await xrpl_functions.get_zrp_balance(config.JACKPOT_ADDR))
    main_embed.add_field(name="Jackpot ZRP value:",
                         value=f"**{j_bal:.2f}**",
                         inline=False)

    try:
        user_bal = float(await xrpl_functions.get_zrp_balance(user_owned_nfts['address']))
        main_embed.add_field(name="Your ZRP balance:",
                             value=f"**{user_bal:.2f}**",
                             inline=False)
    except:
        pass
    # main_embed.set_footer(text=f"Usage guide: \n"
    #                            f"/use revive_potion zerpmon_id\n"
    #                            f"/use mission_refill\n")
    return main_embed


async def zrp_store_callback(interaction: nextcord.Interaction):
    user_id = interaction.user.id
    await interaction.response.defer(ephemeral=True)
    main_embed = CustomEmbed(title="ZRP Store", color=0xfcff82)
    zrp_price = await xrpl_functions.get_zrp_price_api()
    refill_p = config.ZRP_STORE['refill'] / zrp_price
    candy_white_p = config.ZRP_STORE['candy_white'] / zrp_price
    candy_gold_p = config.ZRP_STORE['candy_gold'] / zrp_price
    liquor_p = config.ZRP_STORE['liquor'] / zrp_price
    battle_zone_p = config.ZRP_STORE['battle_zone'] / zrp_price
    name_flair_p = config.ZRP_STORE['name_flair'] / zrp_price
    safari_p = config.ZRP_STORE['safari'] / zrp_price
    equip_p = config.ZRP_STORE['equipment'] / zrp_price

    main_embed.add_field(name="**Zerpmon Equipment**" + '\t🗡️',
                         value=f"Cost: `{equip_p:.2f} ZRP`",
                         inline=False)

    main_embed.add_field(name="**Gym Refill**" + '\t🍵',
                         value=f"Cost: `{refill_p:.2f} ZRP`",
                         inline=False)
    # main_embed.add_field(name='🍬 **CANDY 🍬', value='\u200B', inline=False)
    main_embed.add_field(name="**Power Candy (White)**" + '\t🍬',
                         value=f"Cost: `{candy_white_p:.2f} ZRP`",
                         inline=False)

    main_embed.add_field(name="**Power Candy (Gold)**" + '\t🍭',
                         value=f"Cost: `{candy_gold_p:.2f} ZRP`",
                         inline=False)

    main_embed.add_field(name="**Golden Liquorice**" + '\t🍯',
                         value=f"Cost: `{liquor_p:.2f} ZRP`",
                         inline=False)

    main_embed.add_field(name="**Battle Zones**" + '\t🏟️',
                         value=f"Cost: `{battle_zone_p:.2f} ZRP`",
                         inline=False)

    main_embed.add_field(name="**Name Flair**" + '\t💠',
                         value=f"Cost: `{name_flair_p:.2f} ZRP`",
                         inline=False)

    main_embed.add_field(name="**Safari Trip**" + '\t🎰',
                         value=f"Cost: `{safari_p:.2f} ZRP`",
                         inline=False)

    main_embed.add_field(name=f"\u200B",
                         value=f"Items will be available within a few minutes after transaction is successful",
                         inline=False)

    main_embed.set_footer(text=f"Usage guide: \n"
                               f"/use gym_refill\n"
                               f"/use power_candy_white\n"
                               f"/use power_candy_gold\n"
                               f"/use golden_liquorice")

    sec_embed = await show_zrp_holdings(interaction)

    b0 = Button(label="Buy Safari Trip", style=ButtonStyle.green, emoji='🎰', row=0)
    b1 = Button(label="Buy Gym Refill", style=ButtonStyle.blurple, emoji='🍵', row=0)
    b2 = Button(label="Buy Power Candy (White)", style=ButtonStyle.blurple, emoji='🍬', row=0)
    b3 = Button(label="Buy Power Candy (Gold)", style=ButtonStyle.blurple, emoji='🍭', row=0)
    b4 = Button(label="Buy Golden Liquorice", style=ButtonStyle.green, emoji='🍯', row=1)
    b5 = Button(label="Buy Battle Zones", style=ButtonStyle.green, emoji='🏟️', row=1)
    b6 = Button(label="Buy Zerpmon Equipment", style=ButtonStyle.red, emoji='🗡️', row=1)
    b7 = Button(label="Buy Name Flair", style=ButtonStyle.green, emoji='💠', row=1)
    # user_d = db_query.get_owned(str(user_id))
    # zrp_gift_box, xblade_gift_box = db_query.get_boxes(user_d['address'])
    all_btns = [b0, b1, b2, b3, b4, b5, b6, b7]
    # if zrp_gift_box > 0:
    #     b8 = Button(label="Open Zerpmon Gift Box", style=ButtonStyle.success, emoji='🎁', row=2)
    #     all_btns.append(b8)
    #     b8.callback = lambda i: on_button_click(i, label=b8.label, amount=zrp_gift_box)
    # if xblade_gift_box > 0:
    #     b9 = Button(label="Open Xscape Gift Box", style=ButtonStyle.success, emoji='💝', row=2)
    #     all_btns.append(b9)
    #     b9.callback = lambda i: on_button_click(i, label=b9.label, amount=xblade_gift_box)
    # sec_embed.add_field(name="Zerpmon Gift Box:",
    #                      value=f"**{zrp_gift_box}**"
    #                            + '\t🎁',
    #                      inline=False)
    # sec_embed.add_field(name="Xscape Gift Box:",
    #                     value=f"**{xblade_gift_box}**"
    #                           + '\t💝',
    #                     inline=False)
    view = View()
    for item in all_btns:
        view.add_item(item)
    view.timeout = 120  # Set a timeout of 60 seconds for the view to automatically remove it after the time is up

    # Add the button callback to the button
    b0.callback = lambda i: on_button_click(i, label=b0.label, amount=safari_p)
    b1.callback = lambda i: on_button_click(i, label=b1.label, amount=refill_p)
    b2.callback = lambda i: on_button_click(i, label=b2.label, amount=candy_white_p)
    b3.callback = lambda i: on_button_click(i, label=b3.label, amount=candy_gold_p)
    b4.callback = lambda i: on_button_click(i, label=b4.label, amount=liquor_p)
    b5.callback = lambda i: on_button_click(i, label=b5.label, amount=battle_zone_p)
    b6.callback = lambda i: on_button_click(i, label=b6.label, amount=equip_p)
    b7.callback = lambda i: on_button_click(i, label=b7.label, amount=name_flair_p)

    await interaction.edit_original_message(embeds=[main_embed, sec_embed], view=view)


async def zrp_purchase_callback(_i: nextcord.Interaction, amount, item, safari=False, buy_offer=False, offerId='',
                                token_id='', fee=False, loan=False):
    user_owned_nfts = db_query.get_owned(_i.user.id)

    # Sanity checks

    if user_owned_nfts is None:  # or (len(user_owned_nfts['zerpmons']) == 0 and not loan and not fee):
        await _i.edit_original_message(
            content="Sorry you can't make store/marketplace purchases, as you don't hold a Zerpmon NFT",
            embeds=[], view=View())
        return
    await _i.edit_original_message(content="Generating transaction QR code..." + (
        '\n(**loan fee transaction**)' if fee else ('(**loan payment + fee transaction**)' if loan else '')), embeds=[],
                                   view=View())
    user_id = str(_i.user.id)
    user_address = user_owned_nfts['address']
    if not buy_offer:
        uuid, url, href = await xumm_functions.gen_zrp_txn_url(
            config.LOAN_ADDR if fee or loan else (config.ISSUER['ZRP'] if not safari else config.SAFARI_ADDR),
            user_address, amount)
    else:
        uuid, url, href = await xumm_functions.gen_nft_accept_txn(
            user_address,
            offerId, token_id)
    embed = CustomEmbed(color=0x01f39d,
                        title=f"Please sign the transaction using this QR code or click here (expires <t:{int(time.time()) + 180}:R>).",
                        url=href)

    embed.set_image(url=url)

    await _i.edit_original_message(embed=embed, view=View())
    for i in range(18):
        track_list = config.zrp_purchases
        if fee or loan:
            track_list = config.loan_payers_zrp
        if user_id in track_list and track_list[user_id] == amount or (
                buy_offer and config.eq_ongoing_purchasers[user_address]['accepted'] == True):
            try:
                if not buy_offer:
                    del track_list[user_id]
                    await _i.edit_original_message(embed=CustomEmbed(title="**Success**",
                                                                     description=item if fee or loan else (
                                                                         f"Bought {item}." if 'Equipment' not in item else f'Sent `{amount} ZRP`\nCreating Sell Offer...'))
                                                   )
                else:
                    return user_address, True
            except Exception as e:
                print(traceback.format_exc())
            finally:
                return user_address, True
        await asyncio.sleep(10)
    return user_address, False


async def use_gym_refill_callback(interaction: nextcord.Interaction):
    user = interaction.user
    user_id = user.id
    user_owned_nfts = {'data': db_query.get_owned(user.id), 'user': user.name}

    # Sanity checks
    if user.id in config.ongoing_gym_battles:
        await interaction.send(f"Please wait, Gym Refill can't be used during a Gym Battle.",
                               ephemeral=True)
        return

    for owned_nfts in [user_owned_nfts]:
        if owned_nfts['data'] is None:
            await interaction.send(
                f"Sorry no NFTs found for **{owned_nfts['user']}** or haven't yet verified your wallet", ephemeral=True)
            return

        if 'gym' not in owned_nfts['data'] or 'refill_potion' not in owned_nfts['data']['gym'] or int(
                owned_nfts['data']['gym']['refill_potion']) <= 0:
            return (await zrp_store_callback(interaction))

    saved = db_query.gym_refill(user_id)
    if not saved:
        await interaction.send(
            f"**Failed**",
            ephemeral=True)
        return False
    else:
        await interaction.send("**SUCCESS**", ephemeral=True)


async def use_candy_callback(interaction: nextcord.Interaction, label, next_page=0, amt=1):
    owned_nfts = db_query.get_owned(interaction.user.id)
    if owned_nfts is None:
        await interaction.send(
            f"Sorry no NFTs found for **{interaction.user.mention}** or haven't yet verified your wallet",
            ephemeral=True)
        return

    if 'white' in label.lower():
        if 'white_candy' not in owned_nfts or int(owned_nfts['white_candy']) < amt:
            return (await zrp_store_callback(interaction))
    elif 'gold' in label.lower():
        if 'gold_candy' not in owned_nfts or int(owned_nfts['gold_candy']) < amt:
            return (await zrp_store_callback(interaction))
    else:
        if 'lvl_candy' not in owned_nfts or int(owned_nfts['lvl_candy']) < amt:
            return (await zrp_store_callback(interaction))

    await interaction.response.defer(ephemeral=True)

    async def handle_select_menu(_i: nextcord.Interaction):
        print(_i.data)
        selected_option = _i.data["values"][0]  # Get the selected option
        await _i.response.defer(ephemeral=True)

        if 'white' in label.lower():
            res = db_query.apply_white_candy(_i.user.id, selected_option, amt)
        elif 'gold' in label.lower():
            res = db_query.apply_gold_candy(_i.user.id, selected_option, amt)
        else:
            res = db_query.increase_lvl(_i.user.id, selected_option)

        if res is False:
            await _i.edit_original_message(content="**Failed** Max candy usage reached!", view=View())
        else:
            await _i.edit_original_message(content="**Success**!", view=View())

    user_owned = owned_nfts
    # zerps = {str(k + 100): v for k, v in enumerate(db_query.get_all_z())}
    view = View()
    cards = {k: v for k, v in user_owned['zerpmons'].items()} if user_owned is not None else {}
    # cards = {k: v for k, v in zerps.items()} if user_owned is not None else {}
    key_list = [k for k, v in cards.items()]
    key_list = key_list[next_page * 80:]
    # print(key_list)
    for num in range(math.ceil(len(key_list) / 25)):
        if len(view.children) == 4:
            break
        select_menu = nextcord.ui.StringSelect(placeholder="Which Zerpmon to use it on")
        card_obj = key_list[num * 25:(num + 1) * 25] if num != math.ceil(len(key_list) / 25) - 1 else key_list[
                                                                                                      num * 25:len(
                                                                                                          cards)]
        for i in card_obj:
            select_menu.add_option(label=cards[i]['name'], value=cards[i]['name'])
        view.add_item(select_menu)
        select_menu.callback = handle_select_menu
    if len(key_list) > 80:
        b1 = Button(label='Show more', style=ButtonStyle.green)
        view.add_item(b1)
        b1.callback = lambda _i: use_candy_callback(_i, label, next_page=next_page + 1)
    await interaction.edit_original_message(content="Choose one **zerpmon**:", view=view)


async def send_general_message(guild, text, image):
    try:
        channel = nextcord.utils.get(guild.channels, name='🌐│zerpmon-center')
        await channel.send(content=text + '\n' + image)
    except Exception as e:
        logging.error(f'ERROR: {traceback.format_exc()}')


async def on_button_click(interaction: nextcord.Interaction, label, amount, qty=1, defer=True):
    user_id = interaction.user.id
    addr = db_query.get_owned(user_id)['address']
    amount = round(amount, 2)
    if defer:
        await interaction.response.defer(ephemeral=True)
    match label:
        case "Buy Zerpmon Equipment":
            select_menu = nextcord.ui.StringSelect(placeholder="Select an option")
            found, stored_nfts = await xrpl_functions.get_nfts(config.STORE_ADDR)
            stored_eqs = [nft for nft in stored_nfts if nft["Issuer"] == config.ISSUER["Equipment"]]
            if not found:
                await interaction.edit_original_message(
                    content="**Error** in getting Store Equipment NFTs from XRPL server", embeds=[])
                return
            holdings = []
            nft_data = xrpl_functions.get_nft_metadata([nft['URI'] for nft in stored_eqs], multi=True)
            for nft in stored_eqs:
                holdings.append(nft_data[nft['URI']]['name'])
            holdings = Counter(holdings)
            eqs = db_query.get_all_eqs()
            for i in eqs:
                if i['name'] in holdings:
                    select_menu.add_option(label=i['name'] + f" ({i['type']})", value=i['name'])
            view = View()
            view.add_item(select_menu)
            await interaction.edit_original_message(content="Choose one **equipment**:", embeds=[], view=view)

            async def handle_select_menu(_i: nextcord.Interaction, addr):
                print(_i.data, holdings)
                selected_option = _i.data["values"][0]  # Get the selected option
                await _i.response.defer(ephemeral=True)
                not_bought = db_query.not_bought_eq(addr, selected_option)
                cancelled = False
                if not not_bought:
                    await _i.edit_original_message(content=f"Sorry, you have already bought {selected_option}\n"
                                                           f"`Note: Can only buy 1 of each type from Store`", embeds=[],
                                                   view=View())
                    return
                proceed = check_eq_in_wallet(selected_option, holdings.get(selected_option, 0))
                if not proceed:
                    await _i.edit_original_message(content="Sorry, this equipment have been sold out", embeds=[],
                                                   view=View())
                    return
                if addr in config.eq_ongoing_purchasers:
                    await interaction.edit_original_message(
                        content="**Please wait** you already have an ongoing purchase\nTry again once it's finished",
                        embeds=[], view=View())
                    return
                config.eq_ongoing_purchasers[addr] = {'offer': None, 'accepted': False}
                try:
                    await _i.edit_original_message(
                        content=f"Please wait (Timer: <t:{int(time.time() + 60)}:R>)\n**Creating** sell offer for **{selected_option}** and **confirming** OfferId...",
                        embeds=[],
                        view=View())
                    created, data = await send_equipment(user_id, addr, selected_option, safari=False, random_eq=False,
                                                         price=amount)
                    config.eq_ongoing_purchasers[addr]['offer'] = data[-1]
                    if created:
                        # Make 0 XRP sell offer of equipment NFT
                        # XUMM txn for buying the NFT using ZRP
                        db_query.save_bought_eq(addr, selected_option)
                        addr, success = await zrp_purchase_callback(_i, amount=amount, item=label, buy_offer=True,
                                                                    offerId=data[-1], token_id=data[-2])
                        if success:
                            db_query.update_zrp_stats(burn_amount=amount, distributed_amount=0)
                            await _i.edit_original_message(
                                content=f"Transaction **Successful**, sent {selected_option}\n"
                                        f"https://xrp.cafe/nft/{data[-2]}", embeds=[],
                                view=View())
                        else:
                            await _i.edit_original_message(
                                content="Failed, please make sure to sign the **TXN** within a few minutes", embeds=[],
                                view=View())
                            db_query.remove_token_sent(data[-2])
                            cancelled = await cancel_offer('store', data[-1])
                    else:
                        await _i.edit_original_message(content="Failed, Something went wrong", embeds=[], view=View())
                        db_query.remove_token_sent(data[-2])
                        cancelled = await cancel_offer('store', data[-1])
                except Exception as e:
                    logging.error(f'ERROR while sending EQ: {traceback.format_exc()}')
                    try:
                        db_query.remove_token_sent(data[-2])
                        cancelled = await cancel_offer('store', data[-1])
                    except:
                        logging.error(f'ERROR while cancelling EQ offer during exception: {traceback.format_exc()}')
                finally:
                    del config.eq_ongoing_purchasers[addr]
                    config.eq_purchases[selected_option] -= 1
                    if cancelled:
                        db_query.remove_bought_eq(addr, selected_option)

            # Register the event handler for the select menu
            select_menu.callback = lambda interact: handle_select_menu(interact, addr)
        case "Buy Battle Zones":
            select_menu = nextcord.ui.StringSelect(placeholder="Select an option")
            for i in config.GYMS:
                select_menu.add_option(label=i + f' {config.TYPE_MAPPING[i]}', value=i)
            view = View()
            view.add_item(select_menu)
            await interaction.edit_original_message(content="Choose one **battle zone**:", embeds=[], view=view)

            async def handle_select_menu(_i: nextcord.Interaction):
                print(_i.data)
                selected_option = _i.data["values"][0]  # Get the selected option
                await _i.response.defer(ephemeral=True)  # Defer the response to avoid timeout
                addr, purchased = await zrp_purchase_callback(_i, amount, label.replace('Buy ', ''))
                if purchased:
                    db_query.update_zrp_stats(burn_amount=amount, distributed_amount=0)
                    db_query.update_user_bg(user_id, selected_option)

            # Register the event handler for the select menu
            select_menu.callback = handle_select_menu
        case "Buy Gym Refill":
            addr, purchased = await zrp_purchase_callback(interaction, amount, label.replace('Buy ', ''))
            if purchased:
                db_query.update_zrp_stats(burn_amount=amount, distributed_amount=0)
                db_query.add_gym_refill_potion(addr, 1, True, )
        case "Buy Power Candy (White)" | "Buy Power Candy (Gold)" | "Buy Golden Liquorice":
            select_menu = nextcord.ui.StringSelect(placeholder="Select amount")
            for i in range(1, 11):
                select_menu.add_option(label=str(i), value=str(i))
            view = View()
            view.add_item(select_menu)
            await interaction.edit_original_message(content="Choose:", embeds=[], view=view)

            async def handle_select_menu(_i: nextcord.Interaction):
                print(_i.data)
                selected_option = int(_i.data["values"][0])  # Get the selected option
                await _i.response.defer(ephemeral=True)  # Defer the response to avoid timeout
                amt = amount * selected_option
                addr, purchased = await zrp_purchase_callback(_i, amt, label.replace('Buy ', ''))
                if purchased:
                    db_query.update_zrp_stats(burn_amount=amt, distributed_amount=0)
                    if 'white' in label.lower():
                        db_query.add_white_candy(addr, selected_option, purchased=True, amount=amt)
                    elif 'liquorice' in label.lower():
                        db_query.add_lvl_candy(addr, selected_option, purchased=True, amount=amt)
                    else:
                        db_query.add_gold_candy(addr, selected_option, purchased=True, amount=amt)

            select_menu.callback = handle_select_menu

        case "Buy Safari Trip":
            addr, purchased = await zrp_purchase_callback(interaction, amount * qty,
                                                          label.replace('Buy ', '' if qty == 1 else f'{qty} '),
                                                          safari=True)
            if purchased:
                j_amount = round(amount * qty * 0.2, 2)
                await send_zrp(config.JACKPOT_ADDR, j_amount, 'safari')
                # Run 3 raffles
                rewards = [

                ]
                for i in range(qty):
                    for i in range(3):
                        reward = random.choices(list(SAFARI_REWARD_CHANCES.keys()),
                                                list(SAFARI_REWARD_CHANCES.values()))[0]
                        embed = CustomEmbed(title=f"Safari roll {i + 1}", colour=0xff5722)
                        match reward:
                            # case "no_luck":
                            #     msg = random.choice(config.NOTHING_MSG)
                            #     rewards.append("Gained Nothing")
                            case "zrp":
                                r_int = random.randint(10, 415) / 10
                                s_amount = round(amount * r_int / 100, 2)
                                status = await send_zrp(addr, s_amount, 'safari')
                                msg = random.choice(
                                    config.ZRP_STATEMENTS) + f'\nCongrats, Won `{s_amount} $ZRP`!\n{"`Transaction Successful`" if status else ""}!'
                                rewards.append(f"Gained {s_amount} $ZRP!")
                            case "equipment":
                                db_query.add_equipment(addr, 1)
                                msg = random.choice(config.EQUIPMENT_MSG)
                                success, data, empty = await send_equipment(user_id, addr, label, safari=True,
                                                                            random_eq=True)
                                if empty:
                                    SAFARI_REWARD_CHANCES['equipment'] = 0
                                if success:
                                    rewards.append(f"Gained 1 Equipment({data[0]})!\nhttps://xrp.cafe/nft/{data[-1]}")
                                    description = f'🔥 🔥 **Congratulations** {interaction.user.mention} just won **{data[0]}**\n{data[1]} ! 🔥 🔥\n@everyone'
                                    await send_general_message(guild=interaction.guild, text=description,
                                                               image='')
                                else:
                                    rewards.append(
                                        "Gained 1 Equipment\nFailed, Something went wrong while sending the Sell offer\n"
                                        "Please contact an admin")

                            case "battle_zone" | "name_flair":
                                user_obj = db_query.get_owned(user_id)
                                if reward == "battle_zone":
                                    user_bgs = [i.replace(f'./static/gym/', '').replace('.png', '') for i in
                                                user_obj.get('bgs', [])]
                                    not_owned_bgs = [i for i in config.GYMS if i not in user_bgs]
                                    db_query.update_user_bg(interaction.user.id, random.choice(
                                        not_owned_bgs if len(not_owned_bgs) > 0 else config.GYMS))
                                elif reward == "name_flair":
                                    user_flairs = [i for i in user_obj.get('flair', [])]
                                    not_owned_flairs = [i for i in config.name_flair_list if i not in user_flairs]
                                    db_query.update_user_flair(interaction.user.id, random.choice(
                                        not_owned_flairs if len(not_owned_flairs) > 0 else config.name_flair_list))
                                reward = reward.replace('_', ' ').title()

                                msg = config.COSMETIC_MSG(reward)
                                rewards.append(f"Gained 1 {reward}!")
                            case "candy_white" | "candy_gold" | "candy_level_up":
                                if 'white' in reward:
                                    db_query.add_white_candy(addr, 1)
                                elif 'gold' in reward:
                                    db_query.add_gold_candy(addr, 1)
                                else:
                                    db_query.add_lvl_candy(addr, 1)
                                reward = reward.split('_')[-1].title()
                                msg = config.CANDY_MSG(interaction.user.name,
                                                       'Golden Liquorice' if 'Up' in reward else reward)
                                rewards.append(
                                    f"Gained 1 {'Golden Liquorice' if 'Up' in reward else 'Power Candy (' + reward + ')'}!")
                            case "jackpot":
                                bal = float(await xrpl_functions.get_zrp_balance(config.JACKPOT_ADDR))
                                amount_ = round(bal * 0.8, 2)
                                status = await send_zrp(addr, amount_, 'jackpot')
                                msg = config.JACKPOT_MSG(interaction.user.name,
                                                         amount_) + f'\n{"Transaction Successful" if status else ""}!'
                                rewards.append(f"Won Jackpot {amount_} $ZRP!")
                                description = f'🔥 🔥 **Congratulations** {interaction.user.mention} just won the **Jackpot**(`{amount_} $ZRP`)! 🔥 🔥\n@everyone'
                                await send_general_message(guild=interaction.guild, text=description,
                                                           image='')
                            case "gym_refill":
                                db_query.add_gym_refill_potion(addr, 1, True, )
                                msg = random.choice(config.GYM_REFILL_MSG)
                                rewards.append(f"Gained 1 Gym Refill!")
                            case "revive_potion":
                                db_query.add_revive_potion(addr, 5, False, )
                                msg = random.choice(config.REVIVE_MSG)
                                rewards.append(f"Gained 5 Revive Potions!")
                            case "mission_refill":
                                db_query.add_mission_potion(addr, 5, False, )
                                msg = random.choice(config.MISSION_REFILL_MSG)
                                rewards.append(f"Gained 5 Mission Refills!")
                            case "zerpmon":
                                res, token_id, empty = await send_random_zerpmon(addr, safari=True)
                                if empty:
                                    SAFARI_REWARD_CHANCES['zerpmon'] = 0
                                if token_id[3] == config.ISSUER['TrainerV2']:
                                    msg = f"**{token_id[0]}** bumped into you on your journey! They decided to follow you!"
                                    description = f'🔥 🔥 **Congratulations** {interaction.user.mention} just won **{token_id[0]}** !! 🔥 🔥\n@everyone'
                                else:
                                    msg = config.ZERP_MSG(token_id[0])
                                    description = f'🔥 🔥 **Congratulations** {interaction.user.mention} just caught **{token_id[0]}** !! 🔥 🔥\n@everyone'
                                rewards.append(f"Won {token_id[0]}!")
                                await send_general_message(guild=interaction.guild, text=description,
                                                           image=token_id[1])
                            case _:
                                msg = random.choice(config.NOTHING_MSG)
                                rewards.append("Gained Nothing")
                        embed.description = msg
                        await interaction.send(embed=embed, ephemeral=True)
                        await asyncio.sleep(1)
                    embed = CustomEmbed(title="Summary", colour=0xff5722)
                    path = f'./static/safari/Success {random.randint(1, 14)}.png'
                    file = nextcord.File(path, filename="image.png")
                    embed.set_image(url=f'attachment://image.png')
                    for reward in rewards:
                        embed.add_field(name=reward, value='\u200B', inline=False)
                    view = View()
                    view.timeout = 120
                    b_s = Button(label="Buy another Safari Trip", style=ButtonStyle.green, emoji='🎰', row=0)
                    b_s.callback = lambda i: on_button_click(i, label='Buy Safari Trip', amount=amount)
                    view.add_item(b_s)

                    await interaction.send(embed=embed, file=file, view=view, ephemeral=True)
                    # await interaction.send(view=view, ephemeral=True)
        # case "Open Zerpmon Gift Box":
        #     # Run 1 raffle
        #     amount, _ = db_query.get_boxes(addr)
        #     if amount <= 0:
        #         return
        #     await interaction.send(content='**Gift Box Opening...**', ephemeral=True)
        #     db_query.dec_box(addr, True)
        #     reward = random.choices(list(config.GIFT_BOX_CHANCES.keys()),
        #                             list(config.GIFT_BOX_CHANCES.values()))[0]
        #     embed = CustomEmbed(title=f"Zerpmon Gift Box", colour=0xff5722)
        #     img = None
        #     match reward:
        #         case "zrp":
        #             s_amount = 5
        #             status = await send_zrp(addr, s_amount, 'gift')
        #             msg = random.choice(
        #                 statements.ZRP_GIFT_STATEMENTS) + f'\nCongrats, Won `{s_amount} $ZRP`!\n{"`Transaction Successful`" if status else ""}!'
        #         case "equipment":
        #             res, token_id = await send_random_zerpmon(addr, gift_box=True, issuer=config.ISSUER['Equipment'])
        #             msg = random.choice(
        #                 statements.ZRP_GIFT_STATEMENTS) + f'\nCongrats, Won `{token_id[0]}`!'
        #             if res:
        #                 my_button = f"https://xrp.cafe/nft/{token_id[-1]}"
        #                 msg += f'\n[view]({my_button})'
        #                 img = token_id[1]
        #                 description = f'🔥 🔥 **Congratulations** {interaction.user.mention} just won **{token_id[0]}**\n{token_id[1]} ! 🔥 🔥\n@everyone'
        #                 await send_general_message(guild=interaction.guild, text=description,
        #                                            image='')
        #             else:
        #                 msg += f"\nFailed, Something went wrong while sending the Sell offer\n"\
        #                     "Please contact an admin"
        #         case "zerpmon":
        #             res, token_id = await send_random_zerpmon(addr, gift_box=True)
        #             my_button = f"https://xrp.cafe/nft/{token_id[-1]}"
        #             msg = random.choice(
        #                 statements.ZRP_GIFT_STATEMENTS) + f'\nCongrats, Won `{token_id[0]}`!'
        #             msg += f'\n[view]({my_button})'
        #             img = token_id[1]
        #             description = f'🔥 🔥 **Congratulations** {interaction.user.mention} just caught **{token_id[0]}** !! 🔥 🔥\n@everyone'
        #             await send_general_message(guild=interaction.guild, text=description,
        #                                        image=token_id[1])
        #         case _:
        #             msg = random.choice(config.NOTHING_MSG)
        #     embed.description = msg
        #     view = View()
        #     view.timeout = 120
        #     amount, _ = db_query.get_boxes(addr)
        #     if amount > 0:
        #         b_s = Button(label="Open Zerpmon Gift Box", style=ButtonStyle.success, emoji='🎁', row=2)
        #         b_s.callback = lambda i: on_button_click(i, label=b_s.label, amount=amount)
        #         view.add_item(b_s)
        #     if img is None:
        #         path = f'./static/safari/Success {random.randint(1, 14)}.png'
        #         file = nextcord.File(path, filename="image.png")
        #         embed.set_image(url=f'attachment://image.png')
        #         await interaction.send(embed=embed, ephemeral=True, view=view, file=file)
        #     else:
        #         embed.set_image(url=img)
        #         await interaction.send(embed=embed, view=view, ephemeral=True)
        # case "Open Xscape Gift Box":
        #     _, amount = db_query.get_boxes(addr)
        #     if amount <= 0:
        #         return
        #     await interaction.send(content='**Gift Box Opening...**', ephemeral=True)
        #     db_query.dec_box(addr, False)
        #     # Run 1 raffle
        #     reward = random.choices(list(config.XSCAPE_GIFT_CHANCES.keys()),
        #                             list(config.XSCAPE_GIFT_CHANCES.values()))[0]
        #     embed = CustomEmbed(title=f"Xscape Gift Box", colour=0xc3195d)
        #     img = None
        #     match reward:
        #         case "stx":
        #             s_amount = 5000
        #             status = await send_zrp(addr, s_amount, 'gift', issuer='STX')
        #             msg = random.choice(statements.XSCAPE_GIFT_STATEMENTS) + f'\nCongrats, Won `{s_amount} $STX`!\n{"`Transaction Successful`" if status else ""}!'
        #         case "xblade":
        #             res, token_id = await send_random_zerpmon(addr, gift_box=True, issuer=config.ISSUER['Xblade'])
        #             my_button = f"https://xrp.cafe/nft/{token_id[-1]}"
        #             msg = random.choice(statements.XSCAPE_GIFT_STATEMENTS) + f'\nCongrats, Won `{token_id[0]}`\n[view]({my_button})!'
        #             img = token_id[1]
        #             description = f'🔥 🔥 **Congratulations** {interaction.user.mention} just won **{token_id[0]}** !! 🔥 🔥\n@everyone'
        #             await send_general_message(guild=interaction.guild, text=description,
        #                                        image=token_id[1])
        #         case "legend":
        #             res, token_id = await send_random_zerpmon(addr, gift_box=True, issuer=config.ISSUER['Legend'])
        #             my_button = f"https://xrp.cafe/nft/{token_id[-1]}"
        #             msg = random.choice(statements.XSCAPE_GIFT_STATEMENTS) + f'\nCongrats, Won `{token_id[0]}`\n[view]({my_button})!'
        #             img = token_id[1]
        #             description = f'🔥 🔥 **Congratulations** {interaction.user.mention} just won **{token_id[0]}** !! 🔥 🔥\n@everyone'
        #             await send_general_message(guild=interaction.guild, text=description,
        #                                        image=token_id[1])
        #         case _:
        #             msg = random.choice(config.NOTHING_MSG)
        #     embed.description = msg
        #     view = View()
        #     view.timeout = 120
        #     _, amount = db_query.get_boxes(addr)
        #     if amount > 0:
        #         b_s = Button(label="Open Xscape Gift Box", style=ButtonStyle.success, emoji='💝', row=2)
        #         b_s.callback = lambda i: on_button_click(i, label=b_s.label, amount=amount)
        #         view.add_item(b_s)
        #     if img is None:
        #         path = f'./static/safari/Success {random.randint(1, 14)}.png'
        #         file = nextcord.File(path, filename="image.png")
        #         embed.set_image(url=f'attachment://image.png')
        #         await interaction.send(embed=embed, ephemeral=True, view=view, file=file)
        #     else:
        #         embed.set_image(url=img)
        #         await interaction.send(embed=embed, view=view, ephemeral=True)
        case "Buy Name Flair":
            # Create a select menu with the dropdown options
            select_menu = nextcord.ui.StringSelect(placeholder="Select an option")
            select_menu2 = nextcord.ui.StringSelect(placeholder="more options")
            for i in config.name_flair_list:
                if len(select_menu.options) >= 25:
                    select_menu2.add_option(label=i, value=i)
                else:
                    select_menu.add_option(label=i, value=i)
            view = View()
            view.add_item(select_menu)
            view.add_item(select_menu2)

            # Send a new message with the select menu
            await interaction.edit_original_message(content="Choose one **Name Flair**:", view=view, embeds=[])

            async def handle_select_menu(_i: nextcord.Interaction):
                print(_i.data)
                selected_option = _i.data["values"][0]  # Get the selected option
                await _i.response.defer(ephemeral=True)
                await _i.edit_original_message(content='Selected ✅', view=View(), embeds=[])
                if user_id == 1017889758313197658:
                    db_query.update_user_flair(user_id, selected_option)
                else:
                    addr, purchased = await zrp_purchase_callback(_i, amount, label.replace('Buy ', ''))
                    if purchased:
                        db_query.update_zrp_stats(burn_amount=amount, distributed_amount=0)
                        db_query.update_user_flair(user_id, selected_option)

            # Register the event handler for the select menu
            select_menu.callback = handle_select_menu
            select_menu2.callback = handle_select_menu


async def gift_callback(interaction: nextcord.Interaction, qty: int, user: nextcord.Member, potion_key, potion, fn,
                        item=False):
    user_id = user.id

    user_owned_nfts = {'data': db_query.get_owned(user_id), 'user': user.name}

    # Sanity checks
    if user_id == interaction.user.id:
        await interaction.send(
            f"Sorry you can't gift **Potions/Candies/Battle Zones/Flairs** to yourself.")
        return False

    if interaction.user.id not in config.ADMINS or item:
        sender = db_query.get_owned(interaction.user.id)
        user_qty = sender[potion_key] if potion_key != 'gym_refill' else (sender.get('gym', {})).get('refill_potion', 0)
        if potion_key in ['bg', 'flair']:
            user_qty = len([i for i in user_qty if item in i])
        if sender is None or user_qty < qty:
            await interaction.send(
                f"Sorry you don't have {f'**{item}**' if item else f'**{qty}**'} {potion}.")
            return False
        elif user_owned_nfts['data'] is None:
            await interaction.send(
                f"Sorry **{user.name}** haven't verified their wallet yet.")
            return False
        else:
            # Put potions on hold os user doesn't spam
            if potion_key not in ['bg', 'flair']:
                fn(sender['address'], -qty)
                fn(user_owned_nfts['data']['address'], qty)
            else:
                fn(sender['discord_id'], item, -qty)
                fn(user_id, item, qty)
            await interaction.send(
                f"Successfully gifted {f'**{item}**' if item else f'**{qty}**'} {potion} to **{user.name}**!",
                ephemeral=False)
            return

    for owned_nfts in [user_owned_nfts]:
        if owned_nfts['data'] is None:
            await interaction.send(
                f"Sorry no User found for **{owned_nfts['user']}** or haven't yet verified your wallet", ephemeral=True)
            return

    if potion_key != 'double_xp':
        fn(user_owned_nfts['data']['address'], qty)
    else:
        fn(user_id, )
    await interaction.send(
        f"**Success!**",
        ephemeral=True)


"""LOAN"""


async def loan_listing(interaction: nextcord.Interaction, zerpmon, price, in_xrp, max_days, active_for, min_days, ):
    user = interaction.user
    user_obj = db_query.get_owned(user.id)
    if user_obj is None or zerpmon not in user_obj['zerpmons']:
        await interaction.edit_original_message(
            content=f"**Failed**\nMake sure you hold this Zerpmon and have verified your wallet", view=View())
        return False
    if max_days < min_days:
        await interaction.edit_original_message(
            content=f"**Failed**\nPlease enter valid values (max_days should be greater than min_days)", view=View())
        return False
    zerp = user_obj["zerpmons"][zerpmon]
    nft_id = zerp['token_id']
    xrpl_client = await get_ws_client()
    has_sell_offers = await xrpl_functions.get_sell_offers(client=xrpl_client, nft_id=nft_id)
    if has_sell_offers:
        await interaction.edit_original_message(
            content=f"**Failed**\nMake sure your {zerp['name']} isn't listed on marketplaces or have any open sell offers",
            view=View())
        return False
    # Proceed
    await interaction.edit_original_message(content="Generating transaction QR code for NFT offer...", embeds=[],
                                            view=View())
    user_address = user_obj['address']
    uuid, url, href = await xumm_functions.gen_nft_txn_url(user_address, nft_id, destination=config.LOAN_ADDR)
    embed = CustomEmbed(color=0x01f39d,
                        title=f"Please sign the transaction using this QR code or click here (expires <t:{int(time.time()) + 180}:R>).",
                        url=href)

    embed.set_image(url=url)

    await interaction.edit_original_message(content='', embed=embed, view=View())
    sent = False
    for i in range(18):
        if user_address in config.loan_listings and config.loan_listings[user_address]['tokenId'] == nft_id:
            sent = True
            break
        await asyncio.sleep(10)
    if not sent:
        await interaction.edit_original_message(content='**Failed**, transaction not signed', embeds=[], view=View())
        return
    else:
        user_d = config.loan_listings[user_address].copy()
        del config.loan_listings[user_address]
        zrp_value = round(price if not in_xrp else price / (await xrpl_functions.get_zrp_price_api()), 2)
        addr, status = await zrp_purchase_callback(interaction, zrp_value, item='', fee=True)
        if not status:
            await interaction.edit_original_message(
                content=f"**Failed**\nListing fee transaction not signed", embeds=[],
                view=View())
            return
        listed = db_query.list_for_loan(zerp, zerpmon, user_d['offer'], str(user.id),
                                        user.name, addr, price, active_for, max_days=max_days, min_days=min_days,
                                        xrp=in_xrp)
        if listed:
            db_query.inc_loan_burn(zrp_value)
            if addr not in config.loaners:
                config.loaners[addr] = [nft_id]
            else:
                config.loaners[addr].append(nft_id)
            await interaction.edit_original_message(
                embed=CustomEmbed(title=f'**Success**!', description=f'{zerp["name"]} listed on Loan marketplace',
                                  color=0xe0ffcd),
                content='', view=View())
        else:
            await interaction.edit_original_message(
                content=f'**Failed**, this could happen when the Zerpmon is already listed\nReverting Fee Txn...',
                embeds=[], view=View())
            await send_zrp(user_address, zrp_value, 'loan')


async def loan_marketplace_callback(interaction: nextcord.Interaction, page=1, filters=None):
    user = interaction.user
    filters = {} if filters is None else filters
    count, listings = db_query.get_loan_listings(page_no=page, search_type=filters.get('search_type', ''),
                                                 xrp=filters.get('xrp', None), listed_by=filters.get('listed_by', ''),
                                                 price=filters.get('price', None))
    embed = CustomEmbed(title='Loan Marketplace', description=f'Total listings **{count}**',
                        color=0xe0ffcd)
    view = View(timeout=180, auto_defer=True)

    for idx, listing in enumerate(listings):
        if len(embed.fields) == 24:
            break
        if listing['expires_at'] <= time.time() and listing['accepted_by']['id'] is None:
            db_query.remove_listed_loan(listing['zerpmon_name'], str(user.id))
            continue
        my_button = f"https://xrp.cafe/nft/{listing['token_id']}"
        nft_type = ', '.join([i['value'] for i in listing['zerp_data']['attributes'] if i['trait_type'] == 'Type'])
        active = "🟢" if listing['accepted_by']['id'] is not None else "🔴"
        embed.add_field(name=f"#{(page - 1) * 10 + idx + 1} {active} {listing['zerpmon_name']} ({nft_type})",
                        value=f"> Loanee: {listing['accepted_by']['username']} (for {listing['accepted_days']} days)\n"
                              f"> Listed: <t:{int(listing['listed_at'])}:R>\n" +
                              (f"> Per day cost: {listing['per_day_cost']} " + (
                                  'XRP\n' if listing['xrp'] else 'ZRP\n')) +
                              (f"> Available again : <t:{int(listing['loan_expires_at'])}:R>\n" if listing[
                                                                                                       'loan_expires_at'] is not None else '') +
                              f"> Listing Expires: <t:{int(listing['expires_at'])}:R>\n"
                              f"> Max Loan period: {listing['max_days']} days\n"
                              f"> Min Loan Period: {listing['min_days']} days\n"
                              f"> [view]({my_button})")
        zerp_button = Button(style=ButtonStyle.secondary, label=listing['zerpmon_name'], row=math.ceil(idx / 5))
        zerp_button.callback = lambda i, listing=listing: show_zerp_callback(interaction,
                                                                             zerpmon_name=listing['zerpmon_name'],
                                                                             listing_obj=listing)

        view.add_item(zerp_button)
    is_last_page = (page - 1) * 10 + len(listings) == count
    next_button = Button(style=ButtonStyle.blurple, label='Next page', emoji='⏭️',
                         disabled=True if is_last_page else False, row=3)
    filter_button = Button(style=ButtonStyle.blurple, label='Add filter', emoji='🧰', row=3)
    next_button.callback = lambda i: loan_marketplace_callback(interaction, page + 1, filters=filters)
    filter_button.callback = lambda i: loan_marketplace_filter(interaction)

    view.add_item(next_button)
    view.add_item(filter_button)
    await interaction.edit_original_message(embed=embed, view=view)


async def show_zerp_callback(interaction: nextcord.Interaction, zerpmon_name, listing_obj):
    zerpmon = db_query.get_zerpmon(zerpmon_name.lower().title())
    embed = checks.get_show_zerp_embed(zerpmon, interaction, )
    view = View(timeout=120)
    loan_b = Button(label='Loan Zerpmon', style=ButtonStyle.green, )
    loan_b.callback = lambda i: initiate_loan(i, listing_obj)
    view.add_item(loan_b)
    await interaction.edit_original_message(embed=embed, view=view)


async def initiate_loan(interaction: nextcord.Interaction, listing):
    print(listing)
    if listing['accepted_by']['id'] is not None:
        await interaction.send('**Failed**, someone already took this loan', ephemeral=True)
        return
    if listing['offer'] is None:
        await interaction.edit_original_message(
            content="**Failed**, sorry this listing is inactive as the offer expired")
        return
    modal = nextcord.ui.Modal(title=f"Loan Info ({listing['zerpmon_name']})")
    days = nextcord.ui.TextInput(label='Length of Loan Period (Days)', required=True)
    modal.add_item(days)
    await interaction.response.send_modal(modal)

    async def proceed_loan(i: nextcord.Interaction, ):
        days = int(i.data['components'][0]['components'][0]['value'])
        print(days)
        # if db_query.get_next_ts(days) > listing['expires_at']:
        #     await i.send(
        #         content=f"**Failed**, loan listing expires {listing['expires_at']}\nYou can't loan it for more than that!",
        #         ephemeral=True)
        #     return
        if days < listing['min_days']:
            await i.send(
                content=f"**Failed**, minimum loan period is of {listing['min_days']} days!", ephemeral=True)
            return
        if days > listing['max_days']:
            await i.send(
                content=f"**Failed**, maximum loan period is of {listing['max_days']} days!", ephemeral=True)
            return
        loaner_obj = db_query.get_owned(listing['listed_by']['id'])
        user_obj = db_query.get_owned(interaction.user.id)
        await i.send(content='**Validating NFT offer**!', ephemeral=True)
        offer_valid = await xrpl_functions.get_offer_by_id(listing['offer'], loaner_obj['address'])
        await asyncio.sleep(1)
        # accepted = True
        if not offer_valid:
            await i.edit_original_message(
                content='**Failed**, probably because the Owner has cancelled the sell offer to Bot wallet')
        else:
            await i.edit_original_message(content='**Offer Validated**!')
            await asyncio.sleep(1)
            amount = round(listing['per_day_cost'] * days, 2)
            if listing['xrp']:
                zrp_p = await xrpl_functions.get_zrp_price_api()
                fee_amount = round(listing['per_day_cost'] / zrp_p, 2)
                addr, status = await zrp_purchase_callback(i, item='Loan fee paid', amount=fee_amount, fee=True)
                if not status:
                    await i.edit_original_message(
                        content=f"**Failed**\nLoan fee transaction not signed", embeds=[],
                        view=View())
                    return
                else:
                    db_query.inc_loan_burn(fee_amount)
                    await asyncio.sleep(1)
                    paid = await purchase_callback(interaction, amount, loan=True)
                    if not paid:
                        await i.edit_original_message(
                            content=f"**Failed**\nLoan payment transaction not signed\nReverting fee Txn", embeds=[],
                            view=View())
                        await send_zrp(addr, fee_amount, 'loan')
                        db_query.inc_loan_burn(-fee_amount)
                        return
            else:
                addr, status = await zrp_purchase_callback(i, item='Loan payment + fee paid',
                                                           amount=amount + listing['per_day_cost'], loan=True)
                if not status:
                    await i.edit_original_message(
                        content=f"**Failed**\nLoan payment + fee transaction not signed", embeds=[],
                        view=View())
                    return
                db_query.inc_loan_burn(amount / days)
            accepted = await accept_nft('loan', listing['offer'], sender=loaner_obj['address'],
                                        token=listing['token_id'])
            if accepted:
                loaned = db_query.update_loanee(listing['zerp_data'], listing['serial'],
                                                {'id': user_obj['discord_id'], 'username': i.user.name,
                                                 'address': addr}, days, amount_total=amount - listing['per_day_cost'])
                if loaned:
                    if listing['xrp']:
                        await send_txn(loaner_obj['address'], amount / days, 'loan')
                        await send_txn(loaner_obj['address'], amount / days, 'loan')
                    else:
                        await send_zrp(loaner_obj['address'], round(amount / days, 2), 'loan')
                    await i.edit_original_message(content='', embeds=[CustomEmbed(title='Success',
                                                                                  description=f'**Loaned** {listing["zerpmon_name"]} for **{days}** Days!\nYou can now add it to your Deck')],
                                                  view=View())
            else:
                await i.send(
                    content='Something went wrong while **transferring** this NFT to Bot wallet, please contact an Admin.',
                    ephemeral=True)

    modal.callback = lambda i: proceed_loan(i)


async def loan_marketplace_filter(interaction: nextcord.Interaction):
    filters = {'search_type': '', 'listed_by': '', 'xrp': None, 'price': 10}
    search_type = nextcord.ui.StringSelect(placeholder="Zerpmon Type", custom_id='search_type')
    for i, t in config.TYPE_MAPPING.items():
        if i != '':
            search_type.add_option(label=f'{i} {t}', value=i)
    listed_by = nextcord.ui.UserSelect(placeholder='Listed by', custom_id='listed_by')
    xrp = nextcord.ui.StringSelect(placeholder="Currency", custom_id='xrp')
    xrp.add_option(label='XRP', value='1')
    xrp.add_option(label='ZRP', value='0')
    price = nextcord.ui.StringSelect(placeholder="Max per day cost", custom_id='price')
    for i in range(25):
        price.add_option(label=f'{(i + 1) / 2}')
    submit_button = Button(label='Search', style=ButtonStyle.blurple)
    view = View(timeout=120, auto_defer=True)
    view.add_item(search_type)
    view.add_item(listed_by)
    view.add_item(xrp)
    view.add_item(price)
    view.add_item(submit_button)
    await interaction.edit_original_message(content="Choose **filters**:", embeds=[], view=view)

    async def handle_select(_i: nextcord.Interaction):
        id_ = _i.data['custom_id']
        selected_option = _i.data["values"][0]  # Get the selected option
        try:
            if len(selected_option) < 6:
                selected_option = float(selected_option)
        except:
            pass
        filters[id_] = selected_option

    async def handle_submit(_i: nextcord.Interaction):
        print(f'Filters: {filters}')
        await loan_marketplace_callback(interaction, page=1, filters=filters)

    search_type.callback = handle_select
    listed_by.callback = handle_select
    xrp.callback = handle_select
    price.callback = handle_select
    submit_button.callback = lambda i: handle_submit(i)


async def cancel_loan(interaction: nextcord.Interaction, listing: dict, is_listing: bool):
    amount = round(listing['per_day_cost'] * 5 if not listing['xrp'] else listing['per_day_cost'] * 5 / (
        await xrpl_functions.get_zrp_price_api()), 2)
    if listing['accepted_by']['id']:
        await interaction.followup.send(
            content=f"You will need to pay 5 day fee (`{amount:.2f}`) for an early cancellation of a loan" + (
                ' listing' if is_listing else ''))
        await asyncio.sleep(1)
        addr, success = await zrp_purchase_callback(interaction, amount, 'Loan cancellation fee paid', fee=True)
    else:
        success = True
    sent, addr = False, None
    send_fn = send_txn if listing['xrp'] else send_zrp
    if success:
        await asyncio.sleep(1)
        if is_listing:
            addr = listing['listed_by']['address']
            if listing['accepted_by']['id']:
                await interaction.edit_original_message(
                    content=f"Sending NFT offer to your wallet...")
                sent = await send_nft('loan', addr, listing['token_id'])
                if sent:
                    # db_query.remove_listed_loan(listing['zerpmon_name'], listing['listed_by']['id'])

                    if listing['accepted_by']['id'] is not None:
                        if not listing['xrp']:
                            await send_fn(listing['accepted_by']['address'], listing['amount_pending'] + amount, 'loan')
                        else:
                            await send_fn(listing['accepted_by']['address'], listing['amount_pending'], 'loan')
                            await send_zrp(listing['accepted_by']['address'], amount, 'loan')
                        db_query.cancel_loan(listing['zerpmon_name'], )
                        await interaction.edit_original_message(
                            content=f"Sending pending **${'XRP' if listing['xrp'] else 'ZRP'} (`{listing['amount_pending']}`)** to **{listing['accepted_by']['username']}**")
                    else:
                        db_query.remove_listed_loan(listing['zerpmon_name'], listing['listed_by']['id'])
            else:
                db_query.remove_listed_loan(listing['zerpmon_name'], listing['listed_by']['id'])
                sent = True
        else:
            addr = listing['accepted_by']['address']
            await interaction.edit_original_message(
                content=f"Sending pending **${'XRP' if listing['xrp'] else 'ZRP'} (`{listing['amount_pending']}`)** to your wallet...")

            sent = await send_fn(addr, listing['amount_pending'], 'loan')
            if sent:
                ack = db_query.update_loanee(listing['zerp_data'], listing['serial'],
                                             {'id': None, 'username': None, 'address': None}, days=0, amount_total=0,
                                             loan_ended=True, discord_id=listing['accepted_by']['id'])
                if ack:
                    await send_nft('loan', listing['listed_by']['address'], listing['token_id'])
                    await send_zrp(listing['listed_by']['address'], amount, 'loan')
                    await interaction.edit_original_message(
                        content=f"Sending NFT offer back to {listing['listed_by']['username']}")
        if not sent and listing['accepted_by']['id']:
            await send_zrp(addr, amount, 'loan')
            await interaction.edit_original_message(
                content=f"**Failed**, sending **fee ZRP** back\nPlease try cancelling loan/listing again")
        else:
            await asyncio.sleep(2)
            await interaction.edit_original_message(content=f"**Done**")


"""Boss battles"""


async def boss_callback(user_id, interaction: nextcord.Interaction):
    try:
        db_query.set_boss_battle_t(user_id)
        await interaction.send('Battle beginning!', ephemeral=True)
        winner = await battle_function.proceed_boss_battle(interaction)
    except Exception as e:
        db_query.set_boss_battle_t(user_id, reset_next_t=True)
        logging.error(f'ERROR in gym battle: {traceback.format_exc()}')
