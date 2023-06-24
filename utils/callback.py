import asyncio
import logging
import time
import traceback

import nextcord
from nextcord import ButtonStyle
from nextcord.ui import Button, View

import config
import db_query
import xumm_functions
from utils import checks, battle_function


class CustomEmbed(nextcord.Embed):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.set_footer(text='Zerpmon',
                        icon_url=config.ICON_URL)


async def purchase_callback(_i: nextcord.Interaction, amount, qty=1):
    try:
        await _i.edit(content="Generating transaction QR code...", embeds=[], view=None)
    except:
        await _i.send(content="Generating transaction QR code...", ephemeral=True)
    user_id = str(_i.user.id)
    if amount == config.POTION[0]:
        config.revive_potion_buyers[user_id] = qty
    else:
        config.mission_potion_buyers[user_id] = qty
    send_amt = (amount * qty) if str(user_id) in config.store_24_hr_buyers else (amount * (qty - 1 / 2))
    user_address = db_query.get_owned(_i.user.id)['address']
    uuid, url, href = await xumm_functions.gen_txn_url(config.STORE_ADDR, user_address, send_amt * 10 ** 6)
    embed = CustomEmbed(color=0x01f39d, title=f"Please sign the transaction using this QR code or click here.",
                        url=href)

    embed.set_image(url=url)

    await _i.send(embed=embed, ephemeral=True, )

    for i in range(18):
        if user_id in config.latest_purchases:
            config.latest_purchases.remove(user_id)
            await _i.send(embed=CustomEmbed(title="**Success**",
                                            description=f"Bought **{qty}** {'Revive All Potion' if amount in [8.99, 4.495] else 'Mission Refill Potion'}",
                                            ), ephemeral=True)
        await asyncio.sleep(10)


async def show_store(interaction: nextcord.Interaction):
    user = interaction.user

    user_owned_nfts = db_query.get_owned(user.id)
    main_embed = CustomEmbed(title="Store Holdings", color=0xfcff82)
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

    main_embed.add_field(name="XRP Earned: ",
                         value=f"**{0 if 'xrp_earned' not in user_owned_nfts else user_owned_nfts['xrp_earned']}**"
                         ,
                         inline=False)
    main_embed.set_footer(text=f"Usage guide: \n"
                               f"/use revive_potion zerpmon_id\n"
                               f"/use mission_refill\n")
    return main_embed


async def store_callback(interaction: nextcord.Interaction):
    user_id = interaction.user.id
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

    main_embed.add_field(name=f"\u200B",
                         value="**Purchase Guide**",
                         inline=False)
    main_embed.add_field(name=f"\u200B",
                         value=f"For getting access to one of these potions send the **exact** amount in **XRP** to "
                         ,
                         inline=False)
    main_embed.add_field(name=f"**`{config.STORE_ADDR}`** ",
                         value=f"or use `/buy revive_potion`, `/buy mission_refill` to buy "
                               f"using earned XRP",
                         inline=False)
    main_embed.add_field(name=f"\u200B",
                         value=f"Items will be available within a few minutes after transaction is successful",
                         inline=False)

    main_embed.set_footer(text=f"Usage guide: \n"
                               f"/use revive_potion\n"
                               f"/use mission_refill")

    sec_embed = await show_store(interaction)

    b1 = Button(label="Buy Revive All Potion", style=ButtonStyle.blurple)
    b2 = Button(label="Buy Mission Refill Potion", style=ButtonStyle.blurple)
    view = View()
    view.add_item(b1)
    view.add_item(b2)
    view.timeout = 120  # Set a timeout of 60 seconds for the view to automatically remove it after the time is up

    # Add the button callback to the button
    b1.callback = lambda i: purchase_callback(i, config.POTION[0])
    b2.callback = lambda i: purchase_callback(i, config.MISSION_REFILL[0])

    await interaction.send(embeds=[main_embed, sec_embed], ephemeral=True, view=view)


async def button_callback(user_id, interaction: nextcord.Interaction, loser: int = None,
                          mission_zerpmon_used: bool = False):
    _user_owned_nfts = {'data': db_query.get_owned(user_id), 'user': interaction.user.name}
    _b_num = 0 if 'battle' not in _user_owned_nfts['data'] else _user_owned_nfts['data']['battle']['num']
    if _b_num > 0:
        if _user_owned_nfts['data']['battle']['reset_t'] > time.time() and _b_num >= 10:

            _hours, _minutes = await checks.get_time_left_utc()

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
            button.callback = lambda i: use_missionP_callback(i)
            return
        elif _user_owned_nfts['data']['battle']['reset_t'] < time.time():
            db_query.update_battle_count(user_id, -1)
            _b_num = 0

    _active_zerpmons = [(k, i) for k, i in _user_owned_nfts['data']['zerpmons'].items()
                        if 'active_t' not in i or
                        i['active_t'] < time.time()]
    mission_deck_zerpmons = [] if 'mission_deck' not in _user_owned_nfts['data'] else \
        [k for k in list(_user_owned_nfts['data']['mission_deck'].values()) if k in [s for (s, i) in _active_zerpmons]]

    # print(active_zerpmons[0])
    r_button = Button(label="Revive Zerpmon", style=ButtonStyle.green)
    r_view = View()
    r_view.add_item(r_button)
    r_view.timeout = 120
    r_button.callback = lambda i: use_reviveP_callback(interaction)
    if len(_active_zerpmons) == 0:

        try:
            await interaction.edit(content=
                                   f"Sorry all Zerpmon are resting, please use a **revive** potion to use them "
                                   f"immediately or "
                                   f"wait for their **24hr** resting period",
                                   view=r_view
                                   )
        except:
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
        _battle_z = [] if len(mission_deck_zerpmons) == 0 else \
            [(k, i) for (k, i) in _active_zerpmons if k == mission_deck_zerpmons[0]]
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

    try:
        loser = await battle_function.proceed_mission(interaction, user_id, _battle_z[0], _b_num)
    except Exception as e:
        logging.error(f"ERROR during mission: {e}\n{traceback.format_exc()}")
        return
    finally:
        config.ongoing_missions.remove(user_id)

    button = Button(label="Battle Again" if loser == 2 else "Battle with next Zerpmon", style=ButtonStyle.green)
    view = View()
    view.add_item(button)
    view.timeout = 120

    button2 = Button(label="Use Mission Refill Potion", style=ButtonStyle.green)
    view2 = View()
    view2.add_item(button2)
    view2.timeout = 120
    button2.callback = lambda i: use_missionP_callback(i)

    _b_num += 1
    reset_str = ''
    if _b_num >= 10:
        if _user_owned_nfts['data']['battle']['reset_t'] > time.time():
            _hours, _minutes = await checks.get_time_left_utc()
            reset_str = f' reset time **{_hours}**h **{_minutes}**m'

    sr, nft = _battle_z[0]
    lvl, xp, xp_req, _r, _m = db_query.get_lvl_xp(nft['name'], in_mission=True)
    embed = CustomEmbed(title=f"Level Up ⬆{lvl}" if xp == 0 else f"\u200B",
                        color=0xff5252,
                        )
    my_button = f"https://xrp.cafe/nft/{nft['token_id']}"
    nft_type = ', '.join([i['value'] for i in nft['attributes'] if i['trait_type'] == 'Type'])
    embed.add_field(
        name=f"**{nft['name']}** ({nft_type})",
        value=f'> Level: **{lvl}/30**\n'
              f'> XP: **{xp}/{xp_req}**\n'
              f'> [view]({my_button})', inline=False)
    if xp == 0:
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
                        inline=False)
    embed.set_image(
        url=nft['image'] if "https:/" in nft['image'] else 'https://cloudflare-ipfs.com/ipfs/' + nft[
            'image'].replace("ipfs://", ""))
    await interaction.send(embeds=[embed, CustomEmbed(
        title=f'**Remaining Missions** for the day: `{10 - _b_num}`')] if loser == 2 else [
        CustomEmbed(title=f'**Remaining Missions** for the day: `{10 - _b_num}`' + reset_str)]
                           , view=(View() if loser == 1 else view2) if (10 - _b_num == 0) else view, ephemeral=True)
    button.callback = lambda i: button_callback(user_id, i, loser, mission_zerpmon_used)


async def use_missionP_callback(interaction: nextcord.Interaction):
    user = interaction.user
    user_id = user.id
    user_owned_nfts = {'data': db_query.get_owned(user.id), 'user': user.name}

    # Sanity checks
    if user.id in config.ongoing_battles:
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


async def use_reviveP_callback(interaction: nextcord.Interaction):
    user = interaction.user

    user_owned_nfts = {'data': db_query.get_owned(user.id), 'user': user.name}

    # Sanity checks
    if user.id in config.ongoing_battles:
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
