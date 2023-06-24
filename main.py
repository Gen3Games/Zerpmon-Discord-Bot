import asyncio
import concurrent
import json
import logging
import random
import threading
import time
import traceback
from typing import Optional
import nextcord
from nextcord import SlashOption, ButtonStyle
from nextcord.ui import Button, View
import config
from nextcord.ext import commands
import xumm_functions
import xrpl_functions
import db_query
from utils import battle_function, nft_holding_updater, xrpl_ws, db_cleaner, checks, callback, reset_alert

intents = nextcord.Intents.all()
client = commands.AutoShardedBot(command_prefix="/", intents=intents)

logging.basicConfig(filename='logfile_wrapper.log', level=logging.ERROR,
                    format='%(asctime)s %(levelname)s %(module)s %(funcName)s %(message)s %(lineno)d')


def start_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()


# create a new event loop
new_loop = asyncio.new_event_loop()

# start a new thread to run the event loop
t = threading.Thread(target=start_loop, args=(new_loop,))
t.start()

new_loop.call_soon_threadsafe(new_loop.create_task, xrpl_ws.main())


async def updater():
    await asyncio.create_task(nft_holding_updater.update_nft_holdings(client))


client.loop.create_task(updater())
client.loop.create_task(reset_alert.send_reset_message(client))


class CustomEmbed(nextcord.Embed):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.set_footer(text='Zerpmon',
                        icon_url=config.ICON_URL)


def execute_before_command(ctx: nextcord.Interaction):
    # Code to run before each slash command
    try:
        logging.error(f'COMMAND USED BY: {ctx.user.name}, {ctx.application_command.name}')
    except:
        pass


@client.event
async def on_ready():
    print('Bot connected to Discord!')


@client.event
async def on_disconnect():
    print('Bot disconnected from Discord.')


@client.event
async def on_resumed():
    print('Bot resumed connection with Discord.')


@client.slash_command(name="ping", description="Ping the bot to check if it's online")
async def ping(interaction: nextcord.Interaction):
    execute_before_command(interaction)
    await interaction.send("Pong!")


@client.event
async def on_guild_join(guild):
    # Register slash commands for the newly joined guild
    res = await client.sync_application_commands(guild_id=guild.id)
    print(res, "GuildID: ", guild)


@client.slash_command(name="wallet", description="Verify your XRPL wallet")
async def wallet(interaction: nextcord.Interaction):
    execute_before_command(interaction)
    # Sanity check
    roles = interaction.guild.roles
    z_role = nextcord.utils.get(roles, name="Zerpmon Holder")
    t_role = nextcord.utils.get(roles, name="Trainer")
    if z_role in interaction.user.roles or t_role in interaction.user.roles:
        await interaction.send(f"You are already verified!")
        return

    # Proceed
    await interaction.send(f"Generating a QR code", ephemeral=True)

    uuid, url, href = await xumm_functions.gen_signIn_url()
    embed = CustomEmbed(color=0x01f39d, title=f"Please sign in using this QR code or click here.",
                        url=href)

    embed.set_image(url=url)

    msg = await interaction.send(embed=embed, ephemeral=True, )
    for i in range(120):
        logged_in, address = await xumm_functions.check_sign_in(uuid)

        if logged_in:
            # Sanity check (Dual Discord Account with 1 Wallet)
            wallet_exist = db_query.check_wallet_exist(address)
            if wallet_exist:
                await interaction.send(f"This wallet is already verified!")
                return
            # Proceed
            await interaction.send(f"**Signed in successfully!**", ephemeral=True)

            good_status, nfts = await xrpl_functions.get_nfts(address)

            user_obj = {
                "username": interaction.user.name + "#" + interaction.user.discriminator,
                "discord_id": str(interaction.user.id),
                "guild_id": interaction.guild_id,
                "zerpmons": {},
                "trainer_cards": {},
                "battle_deck": {'0': {}, '1': {}, '2': {}},
            }

            if not good_status:
                # In case the account isn't active or XRP server is down
                await interaction.send(f"**Sorry, encountered an Error!**", ephemeral=True)
                return

            for nft in nfts:

                if nft["Issuer"] == config.ISSUER["Trainer"]:

                    metadata = await xrpl_functions.get_nft_metadata(nft['URI'])
                    serial = nft["nft_serial"]
                    if "Zerpmon Trainers" in metadata['description']:
                        # Add to MongoDB here
                        user_obj["trainer_cards"][serial] = {"name": metadata['name'],
                                                             "image": metadata['image'],
                                                             "attributes": metadata['attributes'],
                                                             "token_id": nft["NFTokenID"],
                                                             }

                if nft["Issuer"] == config.ISSUER["Zerpmon"]:
                    metadata = await xrpl_functions.get_nft_metadata(nft['URI'])
                    serial = nft["nft_serial"]
                    if "Zerpmon " in metadata['description']:
                        # Add to MongoDB here
                        user_obj["zerpmons"][serial] = {"name": metadata['name'],
                                                        "image": metadata['image'],
                                                        "attributes": metadata['attributes'],
                                                        "token_id": nft["NFTokenID"],
                                                        }
            if len(user_obj['zerpmons']) > 0:
                await interaction.user.add_roles(z_role)
            if len(user_obj['trainer_cards']) > 0:
                await interaction.user.add_roles(t_role)
            # Save the address to stop dual accounts
            user_obj['address'] = address
            db_query.save_user(user_obj)
            return
        await asyncio.sleep(1)
    await msg.edit(embed=CustomEmbed(title="QR code **expired** please generate a new one.", color=0x000))


@client.slash_command(name="show", description="Show owned Zerpmon or Trainer cards")
async def show(interaction: nextcord.Interaction):
    execute_before_command(interaction)
    msg = await interaction.send(f"Searching...", ephemeral=True)
    owned_nfts = db_query.get_owned(interaction.user.id)
    # print([(k, v) for k, v in owned_nfts['zerpmons'].items()])

    if owned_nfts is None:
        await msg.edit(f"Sorry no NFTs found or you haven't yet verified your wallet")
        return

    embed = CustomEmbed(title=f"YOUR **TRAINER CARD** HOLDINGS:\n",
                        color=0xff5252,
                        )
    embed2 = CustomEmbed(title=f"YOUR **ZERPMON** HOLDINGS:\n",
                         color=0xff5252,
                         )
    for serial, nft in owned_nfts['trainer_cards'].items():
        my_button = f"https://xrp.cafe/nft/{nft['token_id']}"
        nft_type = ', '.join([i['value'] for i in nft['attributes'] if i['trait_type'] == 'Nature'])

        embed.add_field(
            name=f"#{serial}  **{nft['name']}** ({nft_type})",
            value=f'[view]({my_button})', inline=False)
    # embed.add_field(
    #     name=f"----------------------------------",
    #     value='\u200B', inline=False)

    for serial, nft in owned_nfts['zerpmons'].items():
        lvl, xp, xp_req, _r, _m = db_query.get_lvl_xp(nft['name'])

        my_button = f"https://xrp.cafe/nft/{nft['token_id']}"
        nft_type = ', '.join([i['value'] for i in nft['attributes'] if i['trait_type'] == 'Type'])
        active = "🟢" if 'active_t' not in nft or nft['active_t'] < time.time() else "🔴"
        embed2.add_field(
            name=f"{active}    #{serial}  **{nft['name']}** ({nft_type})",
            value=f'> Level: **{lvl}**\n'
                  f'> XP: **{xp}/{xp_req}**\n'
                  f'> [view]({my_button})', inline=False)

    timg = ""
    # zimg = ""

    # if len(owned_nfts['trainer_cards']) > 0 and len(owned_nfts['zerpmons']) > 0:
    #     timg = list(owned_nfts['trainer_cards'].items())[0][1]['image']
    #     zimg = list(owned_nfts['zerpmons'].items())[0][1]['image']
    #
    # elif len(owned_nfts['zerpmons']) > 0:
    #
    #     zimg = list(owned_nfts['zerpmons'].items())[0][1]['image']
    if len(owned_nfts['trainer_cards']) > 0:
        timg = list(owned_nfts['trainer_cards'].items())[0][1]['image']

    embed.set_image(
        url=timg if "https:/" in timg else 'https://cloudflare-ipfs.com/ipfs/' + timg.replace("ipfs://", ""))
    # embed2.set_image(
    #     url=zimg if "https:/" in zimg else 'https://cloudflare-ipfs.com/ipfs/' + zimg.replace("ipfs://", ""))

    await msg.edit(content="FOUND", embeds=[embed, embed2], )


@client.slash_command(name="battle",
                      description="Friendly battle among Trainers (require: 1 Zerpmon and 1 Trainer card)",
                      )
async def battle(interaction: nextcord.Interaction, opponent: Optional[nextcord.Member] = SlashOption(required=True),
                 type: int = SlashOption(
                     name="picker",
                     choices={"1v1": 1, "2v2": 2, "3v3": 3, "4v4": 4, "5v5": 5},
                 ),
                 ):
    execute_before_command(interaction)
    # msg = await interaction.send(f"Searching...")
    user_id = interaction.user.id
    # Sanity checks
    proceed = await checks.check_battle(user_id, opponent, interaction, battle_nickname='friendly')
    if not proceed:
        return
        #  Proceed with the challenge if check success

    await interaction.send("Battle conditions met", ephemeral=True)
    config.ongoing_battles.append(user_id)
    config.ongoing_battles.append(opponent.id)
    msg = await interaction.channel.send(
        f"**{type}v{type}** Friendly **battle** challenge to {opponent.mention} by {interaction.user.mention}. Click the **swords** to accept!")
    await msg.add_reaction("⚔")
    config.battle_dict[msg.id] = {
        "type": 'friendly',
        "challenger": user_id,
        "username1": interaction.user.mention,
        "challenged": opponent.id,
        "username2": opponent.mention,
        "active": False,
        "channel_id": interaction.channel_id,
        "timeout": time.time() + 60,
        'battle_type': type,
    }

    # Sleep for a while and notify timeout
    await asyncio.sleep(60)
    if msg.id in config.battle_dict and config.battle_dict[msg.id]['active'] == False:
        del config.battle_dict[msg.id]
        await msg.edit("Timed out")
        await msg.add_reaction("❌")
        config.ongoing_battles.remove(user_id)
        config.ongoing_battles.remove(opponent.id)


@client.slash_command(name="mission",
                      description="PvE / Solo Combat missions for Zerpmon holders",
                      )
async def mission(interaction: nextcord.Interaction):
    execute_before_command(interaction)
    user_id = interaction.user.id

    user_owned_nfts = {'data': db_query.get_owned(user_id), 'user': interaction.user.name}

    # Sanity checks

    for owned_nfts in [user_owned_nfts]:
        if owned_nfts['data'] is None:
            await interaction.send(
                f"Sorry no NFTs found for **{owned_nfts['user']}** or haven't yet verified your wallet", ephemeral=True)
            return

        if len(owned_nfts['data']['zerpmons']) == 0:
            await interaction.send(
                f"Sorry **0** Zerpmon found for **{owned_nfts['user']}**, need **1** to start doing missions",
                ephemeral=True
            )
            return

    await callback.button_callback(user_id, interaction, )


@client.slash_command(name="revive",
                      description="Revive Zerpmon (only server admins can use this)",
                      )
async def revive(interaction: nextcord.Interaction, user: Optional[nextcord.Member] = SlashOption(required=True)):
    # msg = await interaction.send(f"Searching...")
    execute_before_command(interaction)
    user_id = user.id

    user_owned_nfts = {'data': db_query.get_owned(user_id), 'user': user.name}

    # Sanity checks

    if interaction.user.id not in config.ADMINS:
        await interaction.send(f"Only Admins can access this command.", ephemeral=True)
        return

    for owned_nfts in [user_owned_nfts]:
        if owned_nfts['data'] is None:
            await interaction.send(
                f"Sorry no NFTs found for **{owned_nfts['user']}** or haven't yet verified your wallet", ephemeral=True)
            return

        if len(owned_nfts['data']['zerpmons']) == 0:
            await interaction.send(
                f"Sorry **0** Zerpmon found for **{owned_nfts['user']}**, need **1** to revive.",
                ephemeral=True)
            return

    await interaction.send(
        f"**Success!**",
        ephemeral=True)
    db_query.reset_respawn_time(user_id)


@client.slash_command(name="gift",
                      description="Gift Potions (only server admins can use this)",
                      )
async def gift(interaction: nextcord.Interaction):
    pass


@gift.subcommand(description="Gift mission refill potion (only server admins can use this)")
async def mission_refill(interaction: nextcord.Interaction, qty: int,
                         user: Optional[nextcord.Member] = SlashOption(required=True)):
    # msg = await interaction.send(f"Searching...")
    execute_before_command(interaction)
    user_id = user.id

    user_owned_nfts = {'data': db_query.get_owned(user_id), 'user': user.name}

    # Sanity checks

    if interaction.user.id not in config.ADMINS:
        await interaction.send(f"Only Admins can access this command.", ephemeral=True)
        return

    for owned_nfts in [user_owned_nfts]:
        if owned_nfts['data'] is None:
            await interaction.send(
                f"Sorry no User found for **{owned_nfts['user']}** or haven't yet verified your wallet", ephemeral=True)
            return

    db_query.add_mission_potion(user_owned_nfts['data']['address'], qty)
    await interaction.send(
        f"**Success!**",
        ephemeral=True)


@gift.subcommand(description="Gift revive all potion (only server admins can use this)")
async def revive_potion(interaction: nextcord.Interaction, qty: int,
                        user: Optional[nextcord.Member] = SlashOption(required=True)):
    # msg = await interaction.send(f"Searching...")
    execute_before_command(interaction)
    user_id = user.id

    user_owned_nfts = {'data': db_query.get_owned(user_id), 'user': user.name}

    # Sanity checks

    if interaction.user.id not in config.ADMINS:
        await interaction.send(f"Only Admins can access this command.", ephemeral=True)
        return

    for owned_nfts in [user_owned_nfts]:
        if owned_nfts['data'] is None:
            await interaction.send(
                f"Sorry no User found for **{owned_nfts['user']}** or haven't yet verified your wallet", ephemeral=True)
            return

    await interaction.send(
        f"**Success!**",
        ephemeral=True)
    db_query.add_revive_potion(user_owned_nfts['data']['address'], qty)


@client.slash_command(name="add",
                      description="Set Zerpmon (for missions or battles)",
                      )
async def add(interaction: nextcord.Interaction):
    # ...
    pass


@add.subcommand(description="Set Trainer for Missions")
async def mission_trainer(interaction: nextcord.Interaction, trainer_name: str = SlashOption("trainer_name"),
                          ):
    """
    Deal with main Trainer
    """
    execute_before_command(interaction)
    user = interaction.user
    check_passed = await checks.check_trainer_cards(interaction, user, trainer_name)
    if check_passed:
        # await interaction.send(
        #     f"**Adding to deck...**",
        #     ephemeral=True)
        saved = db_query.update_mission_trainer(trainer_name, user.id)
        if not saved:
            await interaction.send(
                f"**Failed**, please recheck the ID or make sure you hold this Trainer",
                ephemeral=True)
        else:
            await interaction.send(
                f"**Success**",
                ephemeral=True)


@add.subcommand(description="Set Trainer for specific Battle Decks")
async def trainer_deck(interaction: nextcord.Interaction, trainer_name: str = SlashOption("trainer_name"),
                       deck_number: str = SlashOption(
                           name="deck_number",
                           choices={"1st": '0', "2nd": '1', "3rd": '2'},
                       ),
                       ):
    """
    Deal with Trainer deck
    """
    execute_before_command(interaction)
    user = interaction.user

    check_passed = await checks.check_trainer_cards(interaction, user, trainer_name)
    if check_passed:
        # await interaction.send(
        #     f"**Adding to deck...**",
        #     ephemeral=True)
        saved = db_query.update_trainer_deck(trainer_name, user.id, deck_number)
        if not saved:
            await interaction.send(
                f"**Failed**, please recheck the ID or make sure you hold this Trainer",
                ephemeral=True)
        else:
            await interaction.send(
                f"**Success**",
                ephemeral=True)


@add.subcommand(description="Set Zerpmon for Solo Missions")
async def mission_deck(interaction: nextcord.Interaction, zerpmon_name: str = SlashOption("zerpmon_name"),
                       place_in_deck: int = SlashOption(
                           name="place",
                           choices={"1st": 1, "2nd": 2, "3rd": 3, "4th": 4, "5th": 5, "6th": 6,
                                    "7th": 7, "8th": 8, "9th": 9, "10th": 10, "11th": 11, "12th": 12, "13th": 13,
                                    "14th": 14, "15th": 15, "16th": 16,
                                    "17th": 17, "18th": 18, "19th": 19, "20th": 20
                                    },
                       ),
                       ):
    """
    Deal with 1v1 Zerpmon deck
    """
    execute_before_command(interaction)
    user = interaction.user

    user_owned_nfts = {'data': db_query.get_owned(user.id), 'user': user.name}
    # Sanity checks

    for owned_nfts in [user_owned_nfts]:
        if owned_nfts['data'] is None:
            await interaction.send(
                f"Sorry no NFTs found for **{owned_nfts['user']}** or haven't yet verified your wallet", ephemeral=True)
            return

        if len(owned_nfts['data']['zerpmons']) == 0:
            await interaction.send(
                f"Sorry **0** Zerpmon found for **{owned_nfts['user']}**, need **1** to set inside the deck",
                ephemeral=True)
            return

        if zerpmon_name not in [i for i in
                                list(owned_nfts['data']['zerpmons'].keys())]:
            await interaction.send(
                f"**Failed**, please recheck the ID/Name or make sure you hold this Zerpmon",
                ephemeral=True)
            return

    # await interaction.send(
    #     f"**Adding to deck...**",
    #     ephemeral=True)
    saved = db_query.update_mission_deck(zerpmon_name, place_in_deck, user.id)
    if not saved:
        await interaction.send(
            f"**Failed**, please recheck the ID or make sure you hold this Zerpmon",
            ephemeral=True)
    else:
        await interaction.send(
            f"**Success**",
            ephemeral=True)


@add.subcommand(description="Add Zerpmon to a specific Battle Deck (max 5)")
async def battle_deck(interaction: nextcord.Interaction, zerpmon_name: str = SlashOption("zerpmon_name"),
                      place_in_deck: int = SlashOption(
                          name="place",
                          choices={"1st": 1, "2nd": 2, "3rd": 3, "4th": 4, "5th": 5},
                      ),
                      deck_number: str = SlashOption(
                          name="deck_number",
                          choices={"1st": '0', "2nd": '1', "3rd": '2'},
                      ),
                      ):
    """
    Deal with multi Zerpmon Deck
    """
    execute_before_command(interaction)
    user = interaction.user

    user_owned_nfts = {'data': db_query.get_owned(user.id), 'user': user.name}

    # Sanity checks

    if user.id in [i['id'] for i in config.battle_royale_participants]:
        await interaction.send(
            f"Sorry you can't change your deck while in the middle of a Battle Royale", ephemeral=True)
        return

    for owned_nfts in [user_owned_nfts]:
        if owned_nfts['data'] is None:
            await interaction.send(
                f"Sorry no NFTs found for **{owned_nfts['user']}** or haven't yet verified your wallet", ephemeral=True)
            return

        if len(owned_nfts['data']['zerpmons']) == 0:
            await interaction.send(
                f"Sorry **0** Zerpmon found for **{owned_nfts['user']}**, need **1** to set inside the deck",
                ephemeral=True)
            return
        if zerpmon_name not in [i for i in
                                list(owned_nfts['data']['zerpmons'].keys())]:
            await interaction.send(
                f"**Failed**, please recheck the ID/Name or make sure you hold this Zerpmon",
                ephemeral=True)
            return

    # await interaction.send(
    #     f"**Adding to deck...**",
    #     ephemeral=True)
    saved = db_query.update_battle_deck(str(zerpmon_name), str(deck_number), int(place_in_deck), user.id)
    if not saved:
        await interaction.send(
            f"**Failed**, please recheck the ID or make sure you hold this Zerpmon",
            ephemeral=True)
    else:
        await interaction.send(
            f"**Success**",
            ephemeral=True)


@add.subcommand(description="Set Default Battle Deck")
async def default_deck(interaction: nextcord.Interaction,
                       deck_number: str = SlashOption(
                           name="deck_number",
                           choices={"1st": '0', "2nd": '1', "3rd": '2'},
                       ),
                       ):
    execute_before_command(interaction)
    """
    Deal with default Zerpmon Deck
    """
    user = interaction.user

    user_owned_nfts = {'data': db_query.get_owned(user.id), 'user': user.name}

    # Sanity checks
    if user.id in [i['id'] for i in config.battle_royale_participants]:
        await interaction.send(
            f"Sorry you can't change your deck while in the middle of a Battle Royale", ephemeral=True)
        return

    for owned_nfts in [user_owned_nfts]:
        if owned_nfts['data'] is None:
            await interaction.send(
                f"Sorry no NFTs found for **{owned_nfts['user']}** or haven't yet verified your wallet", ephemeral=True)
            return

    # await interaction.send(
    #     f"**Setting deck...**",
    #     ephemeral=True)
    saved = db_query.set_default_deck(str(deck_number), user.id)
    if saved:
        await interaction.send(
            f"**Success**",
            ephemeral=True)


@client.slash_command(name="show_deck", description="Show selected Zerpmon for Mission and Battle Decks")
async def show_deck(interaction: nextcord.Interaction):
    execute_before_command(interaction)
    msg = await interaction.send(f"Searching...", ephemeral=True)
    owned_nfts = db_query.get_owned(interaction.user.id)
    # print([(k, v) for k, v in owned_nfts['zerpmons'].items()])
    found = False
    if owned_nfts is None:
        await msg.edit(f"Sorry no NFTs found or you haven't yet verified your wallet")
        return

    embed = CustomEmbed(title=f"**Mission** Zerpmon:\n",
                        color=0xff5252,
                        )
    embedT = CustomEmbed(title=f"**Mission** Trainer:\n",
                         color=0xff5252,
                         )
    embeds = []

    if 'mission_deck' not in owned_nfts:
        pass
    else:
        found = True
        deck = owned_nfts['mission_deck']
        if deck == {}:
            embed.title = f"Sorry looks like you haven't selected Zerpmon for Missions"

        else:
            for place, serial in sorted(deck.items(), key=lambda x: int(x[0])):
                nft = owned_nfts['zerpmons'][serial]
                lvl, xp, xp_req, _r, _m = db_query.get_lvl_xp(nft['name'])
                # zerpmon = db_query.get_zerpmon(nft['name'])
                my_button = f"https://xrp.cafe/nft/{nft['token_id']}"
                nft_type = ', '.join([i['value'] for i in nft['attributes'] if i['trait_type'] == 'Type'])
                active = "🟢" if 'active_t' not in nft or nft['active_t'] < time.time() else "🔴"
                embed.add_field(
                    name=f"{active}    #{serial}  **{nft['name']}** ({nft_type})",
                    value=f'> Level: **{lvl}**\n'
                          f'> XP: **{xp}/{xp_req}**\n'
                          f'> [view]({my_button})', inline=False)
            # for move in [i for i in zerpmon['moves'] if i['name'] != ""]:
            #     embed.add_field(
            #         name=f"**{config.COLOR_MAPPING[move['color']]} Move:**",
            #         value=f"> **{move['name']}**\n" + \
            #               (f"> DMG: {move['dmg']}\n" if 'dmg' in move else "") + \
            #               (f"> Stars: {len(move['stars']) * '★'}\n" if 'stars' in move else "") + \
            #               (
            #                   f"> Type: {config.TYPE_MAPPING[move['type'].replace(' ', '')]}\n" if 'type' in move else "")
            #         ,
            #         inline=False)

            # embed.set_image(
            #     url=nft['image'] if "https:/" in nft['image'] else 'https://cloudflare-ipfs.com/ipfs/' + nft[
            #         'image'].replace("ipfs://", ""))
    # embed.add_field(
    #     name=f"----------------------------------",
    #     value='\u200B', inline=False)
    if 'mission_trainer' not in owned_nfts:
        pass
    else:
        found = True
        serial = owned_nfts['mission_trainer']
        if serial == "":
            embedT.title = f"Sorry looks like you haven't selected a Zerpmon for Mission"

        else:
            trainer = owned_nfts['trainer_cards'][serial]
            my_button = f"https://xrp.cafe/nft/{trainer['token_id']}"
            embedT.add_field(
                name=f"**{trainer['name']}**",
                value=f'> [view]({my_button})', inline=False)
            for attr in trainer['attributes']:
                if attr["trait_type"] == 'Trainer Number':
                    continue
                embedT.add_field(name=f'{attr["trait_type"]}',
                                 value=f'{config.TYPE_MAPPING[attr["value"]] if attr["trait_type"] == "Affinity" else attr["value"]}')

    embeds.append(embed)
    embeds.append(embedT)
    if 'battle_deck' not in owned_nfts:
        pass
    else:
        for k, v in owned_nfts['battle_deck'].items():
            print(v)
            found = True
            nfts = {}
            _i = 0
            embed2 = CustomEmbed(title=f"**Battle** Deck #{int(k) + 1 if int(k) != 0 else 'Default'}:\n",
                                 color=0xff5252,
                                 )
            if 'trainer' in v and v['trainer'] != "":
                nfts['trainer'] = owned_nfts['trainer_cards'][v['trainer']]
            while len(nfts) != len(v):
                try:
                    nfts[str(_i)] = owned_nfts['zerpmons'][v[str(_i)]]
                except:

                    pass
                _i += 1
            if len(nfts) == 0:
                embed2.title = f"Sorry looks like you haven't selected any Zerpmon for Battle deck #{int(k) + 1}"

            else:
                for serial, nft in nfts.items():
                    if serial == 'trainer':
                        trainer = nft
                        my_button = f"https://xrp.cafe/nft/{trainer['token_id']}"
                        embed2.add_field(
                            name=f"**{trainer['name']}**",
                            value=f'> [view]({my_button})', inline=False)
                        for attr in trainer['attributes']:
                            if attr["trait_type"] == 'Trainer Number':
                                continue
                            embed2.add_field(name=f'{attr["trait_type"]}',
                                             value=f'{config.TYPE_MAPPING[attr["value"]] if attr["trait_type"] == "Affinity" else attr["value"]}')
                        # embed2.set_image(
                        #     url=trainer['image'] if "https:/" in trainer[
                        #         'image'] else 'https://cloudflare-ipfs.com/ipfs/' +
                        #                       trainer[
                        #                           'image'].replace("ipfs://", ""))
                    else:
                        lvl, xp, xp_req, _r, _m = db_query.get_lvl_xp(nft['name'])
                        # zerpmon = db_query.get_zerpmon(nft['name'])
                        my_button = f"https://xrp.cafe/nft/{nft['token_id']}"
                        nft_type = ', '.join([i['value'] for i in nft['attributes'] if i['trait_type'] == 'Type'])
                        embed2.add_field(
                            name=f"#{int(serial) + 1}  **{nft['name']}** ({nft_type})",
                            value=f'> Level: **{lvl}**\n'
                                  f'> XP: **{xp}/{xp_req}**\n'
                                  f'> [view]({my_button})', inline=False)
            embeds.append(embed2)
    await msg.edit(
        content="FOUND" if found else "No deck found try to use `/add battle` or `/add mission` to create now"
        , embeds=embeds, )


@client.slash_command(name="use",
                      description="Use Revive or Mission Refill potion",
                      )
async def use(interaction: nextcord.Interaction):
    # ...
    pass


@use.subcommand(name="revive_potion", description="Use Revive All Potion to revive all Zerpmon for Solo Missions")
async def use_revive_potion(interaction: nextcord.Interaction):
    execute_before_command(interaction)
    """
        Deal with Reviving
        """
    res = await callback.use_reviveP_callback(interaction)


@use.subcommand(name="mission_refill", description="Use Mission Refill Potion to reset 10 missions for the day")
async def use_mission_refill(interaction: nextcord.Interaction):
    execute_before_command(interaction)
    """
            Deal with Mission refill
            """
    res = await callback.use_missionP_callback(interaction)


# @use.subcommand(description="Claim XRP earned from missions")
# async def claim(interaction: nextcord.Interaction):
#     """
#             Deal with claim
#             """
#     user = interaction.user
#
#     user_owned_nfts = {'data': db_query.get_owned(user.id), 'user': user.name}
#
#     # Sanity checks
#
#     for owned_nfts in [user_owned_nfts]:
#         if owned_nfts['data'] is None:
#             await interaction.send(
#                 f"Sorry no XRP found for **{owned_nfts['user']}** or haven't yet verified your wallet", ephemeral=True)
#             return
#
#         if 'xrp_earned' not in owned_nfts['data'] or owned_nfts['data']['xrp_earned'] == 0:
#             await interaction.send(
#                 f"Sorry **0** XRP found for **{owned_nfts['user']}**.",
#                 ephemeral=True)
#             return
#
#     await interaction.send(
#         f"**Claiming XRP...**",
#         ephemeral=True)
#     saved = await xrpl_ws.send_txn(user_owned_nfts['data']['address'], user_owned_nfts['data']['xrp_earned'], 'reward')
#     db_query.add_xrp(user.id, -user_owned_nfts['data']['xrp_earned'])
#     if not saved:
#         await interaction.send(
#             f"**Failed**, something went wrong while sending the Txn",
#             ephemeral=True)
#     else:
#         await interaction.send(
#             f"**Successfully** claimed `{user_owned_nfts['data']['xrp_earned']}` XRP",
#             ephemeral=True)


@client.slash_command(name="store", description="Show available items inside the Zerpmon store")
async def store(interaction: nextcord.Interaction):
    execute_before_command(interaction)
    await callback.store_callback(interaction)


@client.slash_command(name="buy",
                      description="Buy Revive or Mission Refill potion using XRP",
                      )
async def buy(interaction: nextcord.Interaction):
    # ...
    pass


@buy.subcommand(description="Purchase Revive All Potion using XRP (1 use)")
async def revive_potion(interaction: nextcord.Interaction, quantity: int):
    execute_before_command(interaction)
    user = interaction.user
    user_id = user.id

    user_owned_nfts = {'data': db_query.get_owned(user.id), 'user': user.name}

    # Sanity checks
    await interaction.send("Please wait...", ephemeral=True)
    if quantity <= 0:
        await interaction.send(
            f"Sorry, the quantity can't be less than 1",
            ephemeral=True)
        return
    for owned_nfts in [user_owned_nfts]:
        if owned_nfts['data'] is None:
            await interaction.send(
                f"Sorry no User found named **{owned_nfts['user']}** or haven't yet verified your wallet",
                ephemeral=True)
            return

    await callback.purchase_callback(interaction, config.POTION[0], quantity)


@buy.subcommand(description="Purchase Mission Refill Potion using XRP (10 Missions)")
async def mission_refill(interaction: nextcord.Interaction, quantity: int):
    execute_before_command(interaction)
    user = interaction.user
    user_id = user.id

    user_owned_nfts = {'data': db_query.get_owned(user.id), 'user': user.name}

    # Sanity checks

    await interaction.send("Please wait...", ephemeral=True)
    if quantity <= 0:
        await interaction.send(
            f"Sorry, the quantity can't be less than 1",
            ephemeral=True)
        return
    for owned_nfts in [user_owned_nfts]:
        if owned_nfts['data'] is None:
            await interaction.send(
                f"Sorry no XRP found for **{owned_nfts['user']}** or haven't yet verified your wallet", ephemeral=True)
            return

    await callback.purchase_callback(interaction, config.MISSION_REFILL[0], quantity)


@client.slash_command(name="show_zerpmon", description="Show a Zerpmon's stats")
async def show_zerpmon(interaction: nextcord.Interaction, zerpmon_name_or_nft_id: str):
    execute_before_command(interaction)
    msg = await interaction.send(f"Searching...", ephemeral=True)
    zerpmon = db_query.get_zerpmon(zerpmon_name_or_nft_id.lower().title())
    if zerpmon is None:
        await interaction.send("Sorry please check the Zerpmon name, got nothing with such a name", ephemeral=True)
    else:
        lvl, xp, xp_req, _r, _m = db_query.get_lvl_xp(zerpmon['name'])
        embed = CustomEmbed(title=f"**{zerpmon['name']}**:\n",
                            color=0xff5252,
                            )
        my_button = f"https://xrp.cafe/nft/{zerpmon['nft_id']}"
        nft_type = ', '.join([i['value'] for i in zerpmon['attributes'] if i['trait_type'] == 'Type'])

        embed.add_field(
            name=f"**{nft_type}**",
            value=f'           [view]({my_button})', inline=False)

        embed.add_field(
            name=f"**Level:**",
            value=f"**{lvl}/30**", inline=True)
        embed.add_field(
            name=f"**XP:**",
            value=f"**{xp}/{xp_req}**", inline=True)

        for i, move in enumerate([i for i in zerpmon['moves'] if i['name'] != ""]):
            notes = f"{db_query.get_move(move['name'])['notes']}"

            embed.add_field(
                name=f"**{config.COLOR_MAPPING[move['color']]} Move:**",
                value=f"> **{move['name']}** \n" + \
                      (f"> Status Affect: `{notes}`\n" if notes != '' else "") + \
                      (f"> DMG: {move['dmg']}\n" if 'dmg' in move else "") + \
                      (f"> Stars: {len(move['stars']) * '★'}\n" if 'stars' in move else "") + \
                      (f"> Type: {config.TYPE_MAPPING[move['type'].replace(' ', '')]}\n" if 'type' in move else "") + \
                      f"> Percentage: {move['percent']}%\n",
                inline=False)

        admin_role = nextcord.utils.get(interaction.guild.roles, name="Founders")
        if admin_role in interaction.user.roles:
            embed.add_field(
                name=f"**Total Matches:**",
                value=f"{0 if 'total' not in zerpmon else zerpmon['total']}", inline=False)
            embed.add_field(
                name=f"**Winrate:**",
                value=f"{0 if 'winrate' not in zerpmon else round(zerpmon['winrate'], 2)}%", inline=True)

        embed.set_image(
            url=zerpmon['image'] if "https:/" in zerpmon['image'] else 'https://cloudflare-ipfs.com/ipfs/' + zerpmon[
                'image'].replace("ipfs://", ""))
        await interaction.send(embed=embed, ephemeral=True)


@client.slash_command(name="add_zerpmon", description="Add a newly minted Zerpmon to Database (For Admins)")
async def add_zerpmon(interaction: nextcord.Interaction, zerpmon_name: str, nft_id: str, white_move: str,
                      gold_move: str, purple_move: str, blue_move: str, red_move: str
                      ):
    execute_before_command(interaction)
    admin_role = nextcord.utils.get(interaction.guild.roles, name="Founders")
    if admin_role not in interaction.user.roles:
        await interaction.send("Only admins can add a new Zerpmon.")
        return
    try:
        print(zerpmon_name, nft_id, white_move, gold_move, purple_move, blue_move, red_move)
        zerpmon_obj = {
            'name': zerpmon_name,
            'nft_id': nft_id,
            'moves': (
                json.loads(white_move.replace("'", "\"")),
                json.loads(gold_move.replace("'", "\"")),
                json.loads(purple_move.replace("'", "\"")),
                json.loads(blue_move.replace("'", "\"")),
                json.loads(red_move.replace("'", "\""))
            )
        }

        zerpmon_obj['moves'] = list(zerpmon_obj['moves'])
        check_passed, formatted_object = db_cleaner.check_move_format(zerpmon_obj)
        if not check_passed:
            await interaction.send("Sorry, something went wrong.\n"
                                   f"Please check move format and retry")
        else:
            res = db_query.save_new_zerpmon(zerpmon_obj)
            await interaction.send(res)
            db_cleaner.set_image_and_attrs()
            db_cleaner.clean_attrs()

    except Exception as e:
        tb = traceback.format_exc()
        await interaction.send(f"Sorry, something went wrong.\n"

                               f"Error message: `{e}`\n"

                               f"On line: {tb.splitlines()[-2]}")


@client.slash_command(name="wager_battle",
                      description="Wager Battle between Trainers (XRP or NFTs)",
                      )
async def wager_battle(interaction: nextcord.Interaction):
    # ...
    pass


@wager_battle.subcommand(description="Battle by waging equal amounts of XRP (Winner takes all)")
async def xrp(interaction: nextcord.Interaction, amount: int,
              opponent: Optional[nextcord.Member] = SlashOption(required=True),
              type: int = SlashOption(
                  name="picker",
                  choices={"1v1": 1, "2v2": 2, "3v3": 3, "4v4": 4, "5v5": 5},
              ),
              ):
    execute_before_command(interaction)
    user_id = interaction.user.id
    # Sanity checks

    channel_clean = battle_function.check_battle_happening(interaction.channel_id)
    if not channel_clean:
        await interaction.send(f"Please wait, one battle is already taking place in this channel.",
                               ephemeral=True)
        return

    user_owned_nfts = {'data': db_query.get_owned(user_id), 'user': interaction.user.name}
    opponent_owned_nfts = {'data': db_query.get_owned(opponent.id), 'user': opponent.name}

    print(opponent)

    # print([(k, v) for k, v in owned_nfts['zerpmons'].items()])

    # Sanity checks

    if user_id == opponent.id:
        await interaction.send(f"You want to battle yourself 🥲, sorry that's not allowed.")
        return

    await interaction.send('Checking ...', ephemeral=True)
    proceed = await checks.check_wager_entry(interaction, [user_owned_nfts, opponent_owned_nfts])
    if not proceed:
        return

    #  Proceed with the challenge if check success

    embed = CustomEmbed(title=f"Battle conditions met **{type}v{type}**", color=0x01f39d,
                        description=f'Please send over the required `{amount} XRP` to Bot Wallet\n'
                                    f'{interaction.user.mention}\n'
                                    f'{opponent.mention}\n')
    embed.set_footer(text='Note: Amount will get distributed to the Winner.\n'
                          'If battle timed out XRP will be automatically returned within a few minutes')

    async def button_callback(_i: nextcord.Interaction, amount):
        if _i.user.id in [user_id, opponent.id]:
            await _i.send(content="Generating transaction QR code...", ephemeral=True)
            user_address = db_query.get_owned(_i.user.id)['address']
            uuid, url, href = await xumm_functions.gen_txn_url(config.WAGER_ADDR, user_address, amount * 10 ** 6)
            embed = CustomEmbed(color=0x01f39d,
                                title=f"Please sign the transaction using this QR code or click here.",
                                url=href)

            embed.set_image(url=url)

            await _i.send(embed=embed, ephemeral=True, )

    button = Button(label="SEND XRP", style=ButtonStyle.green)
    view = View()
    view.add_item(button)
    view.timeout = 120
    button.callback = lambda _i: button_callback(_i, amount)

    if user_id in config.ongoing_battles or opponent.id in config.ongoing_battles:
        await interaction.send(f"Please wait, one battle is already taking place for either you or your Opponent.",
                               ephemeral=True)
        return
    msg = await interaction.channel.send(embed=embed, view=view)
    config.ongoing_battles.append(user_id)
    config.ongoing_battles.append(opponent.id)

    config.wager_battles[msg.id] = {
        'type': 'wager',
        "challenger": user_id,
        "username1": interaction.user.mention,
        "challenged": opponent.id,
        "username2": opponent.mention,
        "active": True,
        "channel_id": interaction.channel_id,
        "timeout": time.time() + 120,
    }

    await asyncio.sleep(20)
    # Sleep for a while and notify timeout

    try:
        user_sent, u_msg_sent = False, False
        opponent_sent, o_msg_sent = False, False
        for i in range(12):
            user_sent, opponent_sent = await xrpl_ws.check_amount_sent(amount, user_owned_nfts['data']['address'],
                                                                       opponent_owned_nfts['data']['address'])
            if user_sent and not u_msg_sent:
                embed.add_field(name=f'{interaction.user.mention} ✅', value='\u200B')
                await msg.edit(embed=embed)
                u_msg_sent = True
            if opponent_sent and not o_msg_sent:
                embed.add_field(name=f'{opponent.mention} ✅', value='\u200B')
                await msg.edit(embed=embed)
                o_msg_sent = True
            if user_sent and opponent_sent:
                winner = await battle_function.proceed_battle(msg, config.wager_battles[msg.id], type)
                user_sent, opponent_sent = False, False
                if winner == 1:
                    await msg.reply(f'Sending transaction for **`{amount * 2} XRP`** to {interaction.user.mention}')
                    saved = await xrpl_ws.send_txn(user_owned_nfts['data']['address'],
                                                   amount * 2, 'wager')
                else:
                    await msg.reply(f'Sending transaction for **`{amount * 2} XRP`** to {opponent.mention}')
                    saved = await xrpl_ws.send_txn(opponent_owned_nfts['data']['address'],
                                                   amount * 2, 'wager')
                if not saved:
                    await msg.reply(
                        f"**Failed**, something went wrong while sending the Txn")

                else:
                    await msg.reply(
                        f"**Successfully** sent `{amount * 2}` XRP")
                    del config.wager_senders[user_owned_nfts['data']['address']]
                    del config.wager_senders[opponent_owned_nfts['data']['address']]
                break
            await asyncio.sleep(10)

        if user_sent or opponent_sent:
            await msg.reply(
                f"Preparing to return XRP to {opponent.mention if opponent_sent else interaction.user.mention}.")
        # If users didn't send the wager
        for addr in config.wager_senders.copy():
            if addr in [user_owned_nfts['data']['address'], opponent_owned_nfts['data']['address']]:
                await xrpl_ws.send_txn(addr, config.wager_senders[addr], 'wager')
                del config.wager_senders[addr]

    except Exception as e:
        logging.error(f"ERROR during wager XRP battle: {e}\n{traceback.format_exc()}")
    finally:

        del config.wager_battles[msg.id]
        await msg.edit(embed=CustomEmbed(title="Finished"), view=None)
        config.ongoing_battles.remove(user_id)
        config.ongoing_battles.remove(opponent.id)


@wager_battle.subcommand(description="Battle by waging 1-1 NFT (Winner takes both)")
async def nft(interaction: nextcord.Interaction, your_nft_id: str, opponent_nft_id: str,
              opponent: Optional[nextcord.Member] = SlashOption(required=True),
              type: int = SlashOption(
                  name="picker",
                  choices={"1v1": 1, "2v2": 2, "3v3": 3, "4v4": 4, "5v5": 5},
              ),
              ):
    execute_before_command(interaction)
    user_id = interaction.user.id
    # Sanity checks

    if user_id in config.ongoing_battles or opponent.id in config.ongoing_battles:
        await interaction.send(f"Please wait, one battle is already taking place for either you or your Opponent.",
                               ephemeral=True)
        return

    channel_clean = battle_function.check_battle_happening(interaction.channel_id)
    if not channel_clean:
        await interaction.send(f"Please wait, one battle is already taking place in this channel.",
                               ephemeral=True)
        return

    user_owned_nfts = {'data': db_query.get_owned(user_id), 'user': interaction.user.name}
    opponent_owned_nfts = {'data': db_query.get_owned(opponent.id), 'user': opponent.name}

    print(opponent)
    # print([(k, v) for k, v in owned_nfts['zerpmons'].items()])

    # Sanity checks

    if user_id == opponent.id:
        await interaction.send(f"You want to battle yourself 🥲, sorry that's not allowed.")
        return

    await interaction.send('Checking ...', ephemeral=True)
    proceed = await checks.check_wager_entry(interaction, [user_owned_nfts, opponent_owned_nfts])
    if not proceed:
        return
    url1, name1 = await xrpl_ws.get_nft_data_wager(your_nft_id)
    url2, name2 = await xrpl_ws.get_nft_data_wager(opponent_nft_id)

    async def button_callback(_i: nextcord.Interaction):
        if _i.user.id in [user_id, opponent.id]:
            await _i.send(content="Generating transaction QR code...", ephemeral=True)
            if _i.user.id == user_id:
                nft_id = your_nft_id
            else:
                nft_id = opponent_nft_id
            user_address = db_query.get_owned(_i.user.id)['address']
            uuid, url, href = await xumm_functions.gen_nft_txn_url(user_address, nft_id)
            embed = CustomEmbed(color=0x01f39d,
                                title=f"Please sign the transaction using this QR code or click here.",
                                url=href)

            embed.set_image(url=url)

            await _i.send(embed=embed, ephemeral=True, )

    #  Proceed with the challenge if check success
    embed = CustomEmbed(title="Battle conditions met",
                        description=f'Please send over the required NFTs to Bot Wallet\n', color=0x01f39d)

    embed2 = CustomEmbed(title=f'{interaction.user.mention} send NFT with ID: {your_nft_id}\n', color=0x01f39d)
    embed2.set_image(url1)
    embed2.add_field(name=f'{name1}', value='\u200B')

    embed3 = CustomEmbed(title=f'{opponent.mention} send NFT with ID: {opponent_nft_id}\n', color=0x01f39d)
    embed3.set_image(url2)
    embed3.add_field(name=f'{name2}', value='\u200B')

    embed.set_footer(text='Note: NFTs will get distributed to the Winner.\n'
                          'If battle timed out NFTs will be automatically returned within a few minutes')
    button = Button(label="SEND NFT", style=ButtonStyle.green)
    view = View()
    view.add_item(button)
    view.timeout = 120
    button.callback = lambda _i: button_callback(_i)

    msg = await interaction.channel.send(embeds=[embed, embed2, embed3], view=view)
    config.ongoing_battles.append(user_id)
    config.ongoing_battles.append(opponent.id)

    config.wager_battles[msg.id] = {
        'type': 'wager',
        "challenger": user_id,
        "username1": interaction.user.mention,
        "challenged": opponent.id,
        "username2": opponent.mention,
        "active": True,
        "timeout": time.time() + 120,
    }

    await asyncio.sleep(20)
    # Sleep for a while and notify timeout

    try:
        user_sent, u_msg_sent = False, False
        opponent_sent, o_msg_sent = False, False
        for i in range(16):
            user_sent = await xrpl_ws.check_nft_sent(user_owned_nfts['data']['address'], your_nft_id)
            opponent_sent = await xrpl_ws.check_nft_sent(opponent_owned_nfts['data']['address'], opponent_nft_id)

            if user_sent and not u_msg_sent:
                embed.add_field(name=f'{interaction.user.mention} ✅', value='\u200B')
                await msg.edit(embeds=[embed, embed3])
                u_msg_sent = True
            if opponent_sent and not o_msg_sent:
                embed.add_field(name=f'{opponent.mention} ✅', value='\u200B')
                await msg.edit(embeds=[embed, embed2])
                o_msg_sent = True

            if user_sent and opponent_sent:
                winner = await battle_function.proceed_battle(msg, config.wager_battles[msg.id], type)
                user_sent, opponent_sent = False, False
                if winner == 1:
                    await msg.reply(
                        f'Sending transaction for `{your_nft_id}` and `{opponent_nft_id}` to {interaction.user.mention}')
                    saved = await xrpl_ws.send_nft_tx(user_owned_nfts['data']['address'],
                                                      [your_nft_id, opponent_nft_id])
                else:
                    await msg.reply(
                        f'Sending transaction for `{your_nft_id}` and `{opponent_nft_id}` to {opponent.mention}')
                    saved = await xrpl_ws.send_nft_tx(opponent_owned_nfts['data']['address'],
                                                      [your_nft_id, opponent_nft_id])
                if not saved:
                    await msg.reply(
                        f"**Failed**, something went wrong while sending the Txn")

                else:
                    await msg.reply(
                        f"**Successfully** sent `{your_nft_id}` and `{opponent_nft_id}`")
                    del config.wager_senders[user_owned_nfts['data']['address']]
                    del config.wager_senders[opponent_owned_nfts['data']['address']]
                break
            await asyncio.sleep(10)
        if user_sent:
            await msg.reply(
                f"Preparing to return NFT to {interaction.user.mention}.")
        elif opponent_sent:
            await msg.reply(
                f"Preparing to return NFT to {opponent.mention}.")
        # If users didn't send the wager
        for addr in config.wager_senders.copy():
            if addr in [user_owned_nfts['data']['address'], opponent_owned_nfts['data']['address']]:
                await xrpl_ws.send_nft_tx(addr,
                                          [config.wager_senders[addr]])
                del config.wager_senders[addr]

    except Exception as e:
        logging.error(f"ERROR during NFT battle: {e}\n{traceback.format_exc()}")
    finally:

        del config.wager_battles[msg.id]
        await msg.edit(embed=CustomEmbed(title="Finished"), view=None)
        config.ongoing_battles.remove(user_id)
        config.ongoing_battles.remove(opponent.id)


@wager_battle.subcommand(description="Battle Royale by waging equal amounts of XRP (Winner takes all)")
async def battle_royale(interaction: nextcord.Interaction, amount: int):
    execute_before_command(interaction)
    await interaction.send("Checking conditions...", ephemeral=True)
    if config.battle_royale_started or len(config.battle_royale_participants) > 0:
        await interaction.send("Please wait another Battle Royale is already in progress.")
        return
    channel_clean = battle_function.check_battle_happening(interaction.channel_id)
    if not channel_clean:
        await interaction.send("Please wait another Battle is already taking place in this channel.")
        return

    config.battle_royale_started = True

    button = Button(label="SEND XRP", style=ButtonStyle.green)
    view = View()
    view.add_item(button)
    view.timeout = 300
    msg = await interaction.channel.send(
        embed=CustomEmbed(description="**Wager Battle Royale** started\n"
                                      f'Please send over the required `{amount} XRP` to Bot Wallet to participate\n'
                                      f"Time left: `{5 * 60}s`", colour=0xf70776), view=view)

    async def wager_battle_r_callback(_i: nextcord.Interaction, amount):
        user_id = _i.user.id
        if user_id in config.ongoing_battles:
            await interaction.send(f"Please wait, one battle is already taking place for either you or your Opponent.",
                                   ephemeral=True)
            return
        if user_id:
            user = db_query.get_owned(user_id)
            user_owned_nfts = {'data': user, 'user': _i.user.name}
            proceed = await checks.check_wager_entry(interaction, [user_owned_nfts])
            if not proceed:
                return
            await _i.send(content="Generating transaction QR code...", ephemeral=True)
            user_address = db_query.get_owned(_i.user.id)['address']
            uuid, url, href = await xumm_functions.gen_txn_url(config.WAGER_ADDR, user_address, amount * 10 ** 6)
            embed = CustomEmbed(color=0x01f39d,
                                title=f"Please sign the transaction using this QR code or click here.",
                                url=href)

            embed.set_image(url=url)

            await _i.send(embed=embed, ephemeral=True, )
            addr = user['address']
            for i in range(15):
                if addr in config.wager_senders:
                    if config.wager_senders[addr] == amount and user_id not in [i['id'] for i in
                                                                                config.battle_royale_participants]:
                        config.battle_royale_participants.append(
                            {'id': user_id, 'username': _i.user.mention, 'address': addr})
                        del config.wager_senders[addr]
                        await _i.send(embed=CustomEmbed(title="**Success**",
                                                        description=f"Entered in Wager Battle Royale",
                                                        ), ephemeral=True)
                        break
                await asyncio.sleep(20)

    button.callback = lambda _i: wager_battle_r_callback(_i, amount)

    try:
        for i in range(6 * 5):
            await asyncio.sleep(10)
            if len(config.battle_royale_participants) >= 50:
                break
            await msg.edit(
                embed=CustomEmbed(description=f"**Wager Battle Royale** started\n"
                                              f'Please send over the required `{amount} XRP` to Bot Wallet to participate\n'
                                              f"Time left: `{5 * 60 - ((i + 1) * 10)}s`\n"
                                              f"Participants: `{len(config.battle_royale_participants)}`\n"
                                              f"Winner gets: `{len(config.battle_royale_participants) * amount} XRP`",
                                  colour=0xf70776))
        if len(config.battle_royale_participants) <= 1:
            await msg.edit(embed=CustomEmbed(description="Battle **timed out**"), view=None)
            for user in config.battle_royale_participants:
                await xrpl_ws.send_txn(user["address"],
                                       amount, 'wager')
            config.battle_royale_participants = []
            config.battle_royale_started = False
            return
        config.battle_royale_started = False
        await msg.edit(embed=CustomEmbed(description="Battle **beginning**"), view=None)
        total_amount = len(config.battle_royale_participants) * amount
        while len(config.battle_royale_participants) > 1:
            random_ids = random.sample(config.battle_royale_participants, 2)
            # Remove the selected IDs from the array
            config.battle_royale_participants = [id_ for id_ in config.battle_royale_participants if
                                                 id_ not in random_ids]
            config.ongoing_battles.append(random_ids[0]['id'])
            config.ongoing_battles.append(random_ids[1]['id'])

            battle_instance = {
                "type": 'friendly',
                "challenger": random_ids[0]['id'],
                "username1": random_ids[0]['username'],
                "challenged": random_ids[1]['id'],
                "username2": random_ids[1]['username'],
                "active": True,
                "channel_id": interaction.channel_id,
                "timeout": time.time() + 60,
                'battle_type': 1,
            }
            config.battle_dict[msg.id] = battle_instance

            try:

                winner = await battle_function.proceed_battle(msg, battle_instance,
                                                              battle_instance['battle_type'])
                if winner == 1:
                    config.battle_royale_participants.append(random_ids[0])
                elif winner == 2:
                    config.battle_royale_participants.append(random_ids[1])
            except Exception as e:
                logging.error(f"ERROR during friendly battle: {e}\n{traceback.format_exc()}")
                await interaction.send('Something went wrong during this match, returning both participants `XRP`')
                for user in [random_ids[0], random_ids[0]]:
                    await xrpl_ws.send_txn(user["address"],
                                           amount, 'wager')
                    total_amount -= amount
            finally:
                config.ongoing_battles.remove(random_ids[0]['id'])
                config.ongoing_battles.remove(random_ids[1]['id'])
                del config.battle_dict[msg.id]

        await msg.channel.send(
            f"**CONGRATULATIONS** **{config.battle_royale_participants[0]['username']}** on winning the Wager Battle Royale!")

        await msg.reply(
            f'Sending transaction for **`{total_amount} XRP`** to {config.battle_royale_participants[0]["username"]}')
        saved = await xrpl_ws.send_txn(config.battle_royale_participants[0]["address"],
                                       total_amount, 'wager')
        if not saved:
            await msg.reply(
                f"**Failed**, something went wrong while sending the Txn")

        else:
            await msg.reply(
                f"**Successfully** sent `{total_amount}` XRP")
    finally:
        config.battle_royale_participants = []
        config.battle_royale_started = False


@client.slash_command(name="show_leaderboard",
                      description="Shows Leaderboard",
                      )
async def show_leaderboard(interaction: nextcord.Interaction):
    pass


@show_leaderboard.subcommand(description="Show PvE Leaderboard")
async def pve(interaction: nextcord.Interaction):
    execute_before_command(interaction)
    # ...
    users = db_query.get_top_players(interaction.user.id)
    embed = CustomEmbed(color=0x01f39d,
                        title=f"PvE LEADERBOARD")

    for i, user in enumerate(users):
        if i == 10:
            msg = '#{0:<4} {1:<30} W/L : {2:<2}/{3:>2}'.format(user['rank'], user['username'], user['win'],
                                                               user['loss'])
            print(msg)
            embed.add_field(name=f'`{msg}`', value=f"\u200B", inline=False)
        else:
            msg = '#{0:<4} {1:<30} W/L : {2:<2}/{3:>2}'.format(i + 1, user['username'], user['win'], user['loss'])
            embed.add_field(name=f'`{msg}`', value=f"\u200B", inline=False)

    await interaction.send(embed=embed, ephemeral=True)


@show_leaderboard.subcommand(description="Show PvP Leaderboard")
async def pvp(interaction: nextcord.Interaction):
    execute_before_command(interaction)
    # ...
    users = db_query.get_pvp_top_players(interaction.user.id)
    embed = CustomEmbed(color=0x01f39d,
                        title=f"PvP LEADERBOARD")

    for i, user in enumerate(users):
        if i == 10:
            msg = '#{0:<4} {1:<30} W/L : {2:<2}/{3:>2}'.format(user['rank'], user['username'], user['pvp_win'],
                                                               user['pvp_loss'])
            embed.add_field(name=f'`{msg}`', value=f"\u200B", inline=False)
        else:
            msg = '#{0:<4} {1:<30} W/L : {2:<2}/{3:>2}'.format(i + 1, user['username'], user['pvp_win'],
                                                               user['pvp_loss'])
            embed.add_field(name=f'`{msg}`', value=f"\u200B", inline=False)

    await interaction.send(embed=embed, ephemeral=True)


@client.slash_command(name='battle_royale', description='Start Battle Royale -> 1 Zerpmon from each player ( max 50 )',
                      )
async def battle_royale(interaction: nextcord.Interaction, start_after: int = SlashOption(
    name="start_after",
    choices={"1 min": 1, "2 min": 2, "3 min": 3},
), ):
    execute_before_command(interaction)
    await interaction.send("Checking conditions...", ephemeral=True)
    if config.battle_royale_started or len(config.battle_royale_participants) > 0:
        await interaction.send("Please wait another Battle Royale is already in progress.")
        return
    channel_clean = battle_function.check_battle_happening(interaction.channel_id)
    if not channel_clean:
        await interaction.send("Please wait another Battle is already taking place in this channel.")
        return

    config.battle_royale_started = True
    msg = await interaction.channel.send(
        f"**Battle Royale** started. Click the **check mark** to enter!\nTime left: `{start_after * 60}s`")
    await msg.add_reaction("✅")
    for i in range(6 * start_after):
        await asyncio.sleep(10)
        if len(config.battle_royale_participants) >= 50:
            break
        await msg.edit(
            f"**Battle Royale** started. Click the **check mark** to enter!\nTime left: `{start_after * 60 - ((i + 1) * 10)}s`")
    if len(config.battle_royale_participants) <= 1:
        await msg.edit(content="Battle **timed out**")
        config.battle_royale_participants = []
        config.battle_royale_started = False
        return
    config.battle_royale_started = False
    await msg.edit(content="Battle **beginning**")
    while len(config.battle_royale_participants) > 1:
        random_ids = random.sample(config.battle_royale_participants, 2)
        # Remove the selected players from the array
        config.battle_royale_participants = [id_ for id_ in config.battle_royale_participants if id_ not in random_ids]
        config.ongoing_battles.append(random_ids[0]['id'])
        config.ongoing_battles.append(random_ids[1]['id'])

        battle_instance = {
            "type": 'friendly',
            "challenger": random_ids[0]['id'],
            "username1": random_ids[0]['username'],
            "challenged": random_ids[1]['id'],
            "username2": random_ids[1]['username'],
            "active": True,
            "channel_id": interaction.channel_id,
            "timeout": time.time() + 60,
            'battle_type': 1,
        }
        config.battle_dict[msg.id] = battle_instance

        try:

            winner = await battle_function.proceed_battle(msg, battle_instance,
                                                          battle_instance['battle_type'])
            if winner == 1:
                config.battle_royale_participants.append(random_ids[0])
            elif winner == 2:
                config.battle_royale_participants.append(random_ids[1])
        except Exception as e:
            logging.error(f"ERROR during friendly battle: {e}\n{traceback.format_exc()}")
        finally:
            config.ongoing_battles.remove(random_ids[0]['id'])
            config.ongoing_battles.remove(random_ids[1]['id'])
            del config.battle_dict[msg.id]

    await msg.channel.send(
        f"**CONGRATULATIONS** **{config.battle_royale_participants[0]['username']}** on winning the Battle Royale!")
    config.battle_royale_participants = []


@client.slash_command(name='trade_nft', description="Trade 1-1 NFT")
async def trade_nft(interaction: nextcord.Interaction, your_nft_id: str, opponent_nft_id: str,
                    opponent: Optional[nextcord.Member] = SlashOption(required=True),
                    ):
    execute_before_command(interaction)
    user_id = interaction.user.id

    # Sanity
    if your_nft_id == opponent_nft_id:
        await interaction.send("Sorry, you are trying to Trade a single NFT 🥲, this trade isn't possible in this "
                               "Planet yet.")
    #
    user_owned_nfts = db_query.get_owned(user_id)
    opponent_owned_nfts = db_query.get_owned(opponent.id)

    url1, name1 = await xrpl_ws.get_nft_data_wager(your_nft_id)
    url2, name2 = await xrpl_ws.get_nft_data_wager(opponent_nft_id)

    async def button_callback(_i: nextcord.Interaction):
        if _i.user.id in [user_id, opponent.id]:
            await _i.send(content="Generating transaction QR code...", ephemeral=True)
            if _i.user.id == user_id:
                nft_id = your_nft_id
            else:
                nft_id = opponent_nft_id
            user_address = db_query.get_owned(_i.user.id)['address']
            uuid, url, href = await xumm_functions.gen_nft_txn_url(user_address, nft_id)
            embed = CustomEmbed(color=0x01f39d,
                                title=f"Please sign the transaction using this QR code or click here.",
                                url=href)

            embed.set_image(url=url)

            await _i.send(embed=embed, ephemeral=True, )

    #  Proceed with the challenge if check success
    embed = CustomEmbed(title="Trade conditions met",
                        description=f'Please send over the required NFTs to Bot Wallet\n', color=0x01f39d)

    embed2 = CustomEmbed(description=f'{interaction.user.mention} send NFT with ID: {your_nft_id}\n', color=0x01f39d)
    embed2.set_image(url1)
    embed2.add_field(name=f'{name1}', value='\u200B')

    embed3 = CustomEmbed(description=f'{opponent.mention} send NFT with ID: {opponent_nft_id}\n', color=0x01f39d)
    embed3.set_image(url2)
    embed3.add_field(name=f'{name2}', value='\u200B')

    embed.set_footer(text='Note:'
                          'If trade timed out NFTs will be automatically returned within a few minutes')
    button = Button(label="SEND NFT", style=ButtonStyle.green)
    view = View()
    view.add_item(button)
    view.timeout = 120
    button.callback = lambda _i: button_callback(_i)

    msg = await interaction.channel.send(embeds=[embed, embed2, embed3], view=view)

    await asyncio.sleep(20)
    # Sleep for a while and notify timeout

    try:
        user_sent, u_msg_sent = False, False
        opponent_sent, o_msg_sent = False, False
        for i in range(16):
            user_sent = await xrpl_ws.check_nft_sent(user_owned_nfts['address'], your_nft_id)
            opponent_sent = await xrpl_ws.check_nft_sent(opponent_owned_nfts['address'], opponent_nft_id)

            if user_sent and not u_msg_sent:
                embed.add_field(name=f'{interaction.user.mention} ✅', value='\u200B')
                await msg.edit(embeds=[embed, embed3])
                u_msg_sent = True
            if opponent_sent and not o_msg_sent:
                embed.add_field(name=f'{opponent.mention} ✅', value='\u200B')
                await msg.edit(embeds=[embed, embed2])
                o_msg_sent = True

            if user_sent and opponent_sent:
                user_sent, opponent_sent = False, False

                await msg.reply(
                    f'Sending transaction for `{your_nft_id}` to {opponent.mention} and `{opponent_nft_id}` to {interaction.user.mention}')
                saved1 = await xrpl_ws.send_nft_tx(user_owned_nfts['address'],
                                                   [opponent_nft_id])

                saved2 = await xrpl_ws.send_nft_tx(opponent_owned_nfts['address'],
                                                   [your_nft_id])
                if not (saved1 and saved2):
                    await msg.reply(
                        f"**Failed**, something went wrong while sending the Txn")

                else:
                    await msg.reply(
                        f"**Successfully** sent `{your_nft_id}` and `{opponent_nft_id}`")
                    del config.wager_senders[user_owned_nfts['address']]
                    del config.wager_senders[opponent_owned_nfts['address']]
                break
            await asyncio.sleep(10)
        if user_sent:
            await msg.reply(
                f"Preparing to return NFT to {interaction.user.mention}.")
            saved1 = await xrpl_ws.send_nft_tx(user_owned_nfts['address'],
                                               [your_nft_id])
            del config.wager_senders[user_owned_nfts['address']]
        elif opponent_sent:
            await msg.reply(
                f"Preparing to return NFT to {opponent.mention}.")
            saved2 = await xrpl_ws.send_nft_tx(opponent_owned_nfts['address'],
                                               [opponent_nft_id])
            del config.wager_senders[opponent_owned_nfts['address']]

    except Exception as e:
        logging.error(f"ERROR during NFT Trade: {e}\n{traceback.format_exc()}")
    finally:
        await msg.edit(embed=CustomEmbed(title="Finished"), view=None)


# RANKED COMMANDS

@client.slash_command(name="ranked_battle",
                      description="3v3 Ranked battle among Trainers (require: 3 Zerpmon and 1 Trainer card)",
                      )
async def ranked_battle(interaction: nextcord.Interaction,
                        opponent: Optional[nextcord.Member] = SlashOption(required=True), ):
    execute_before_command(interaction)
    # msg = await interaction.send(f"Searching...")
    user_id = interaction.user.id
    # Sanity checks
    proceed = await checks.check_battle(user_id, opponent, interaction, battle_nickname='Ranked')
    if not proceed:
        return
        #  Proceed with the challenge if check success

    await interaction.send("Ranked Battle conditions met", ephemeral=True)
    config.ongoing_battles.append(user_id)
    config.ongoing_battles.append(opponent.id)
    msg = await interaction.channel.send(
        f"**3v3** Ranked **battle** challenge to {opponent.mention} by {interaction.user.mention}. Click the **swords** to accept!")
    await msg.add_reaction("⚔")
    config.battle_dict[msg.id] = {
        "type": 'ranked',
        "challenger": user_id,
        "username1": interaction.user.mention,
        "challenged": opponent.id,
        "username2": opponent.mention,
        "active": False,
        "channel_id": interaction.channel_id,
        "timeout": time.time() + 60,
        'battle_type': 3,
    }

    # Sleep for a while and notify timeout
    await asyncio.sleep(60)
    if msg.id in config.battle_dict and config.battle_dict[msg.id]['active'] == False:
        del config.battle_dict[msg.id]
        await msg.edit("Timed out")
        await msg.add_reaction("❌")
        config.ongoing_battles.remove(user_id)
        config.ongoing_battles.remove(opponent.id)


@client.slash_command(name="view",
                      description="Shows Rank Leaderboard",
                      )
async def view_main(interaction: nextcord.Interaction):
    pass


@view_main.subcommand(name="ranked", description="Show your Ranked Leaderboard")
async def view_rank(interaction: nextcord.Interaction):
    execute_before_command(interaction)
    # ...
    users = db_query.get_ranked_players(interaction.user.id)
    embed = CustomEmbed(color=0x01f39d,
                        title=f"Ranked LEADERBOARD")

    for i, user in enumerate(users):
        if str(interaction.user.id) == user['discord_id']:
            msg = '#{0:<4} {1:<20} TIER: {2:<12} ZP : {3:>2}'.format(user['ranked'], user['username'],
                                                                     user['rank']['tier'],
                                                                     user['rank']['points'])
            print(msg)
            embed.add_field(name=f'`{msg}`', value=f"\u200B", inline=False)
        else:
            msg = '#{0:<4} {1:<20} TIER: {2:<12} ZP : {3:>2}'.format(user['ranked'], user['username'],
                                                                     user['rank']['tier'],
                                                                     user['rank']['points'])
            embed.add_field(name=f'`{msg}`', value=f"\u200B", inline=False)

    await interaction.send(embed=embed, ephemeral=True)


# RANKED COMMANDS

# Reaction Tracker

@client.event
async def on_reaction_add(reaction: nextcord.Reaction, user: nextcord.User):
    print(f'{user.name} reacted with {reaction.emoji}.')
    if reaction.emoji == "⚔":
        for _id, battle_instance in config.battle_dict.copy().items():
            if user.id == battle_instance["challenged"] and _id == reaction.message.id and battle_instance[
                "type"] in ['friendly', 'ranked']:
                # Battle accepted
                try:
                    config.battle_dict[_id]['active'] = True
                    if battle_instance["type"] == 'friendly':
                        await reaction.message.edit(content="Battle **beginning**")
                        await battle_function.proceed_battle(reaction.message, battle_instance,
                                                             battle_instance['battle_type'])
                    else:
                        await reaction.message.edit(content="Ranked Battle **beginning**")
                        winner = await battle_function.proceed_battle(reaction.message, battle_instance,
                                                                      battle_instance['battle_type'])
                        points1, t1, new_rank1 = db_query.update_rank(battle_instance["challenger"],
                                                                      True if winner == 1 else False)
                        points2, t2, new_rank2 = db_query.update_rank(battle_instance["challenged"],
                                                                      True if winner == 2 else False)
                        embed = CustomEmbed(title="Match Result", colour=0xfacf5a,
                                            description=f"{battle_instance['username1']}vs{battle_instance['username2']}")
                        embed.add_field(name='\u200B', value='\u200B')
                        embed.add_field(name='🏆 WINNER 🏆',
                                        value=battle_instance['username1'] if winner == 1 else battle_instance[
                                            'username2'],
                                        inline=False)
                        embed.add_field(
                            name=f"{t1['tier'] if winner == 1 else t2['tier']} {'⭐ Rank Up `⬆` ⭐' if (new_rank1 if winner == 1 else new_rank2) is not None else ''}",
                            value=f"{t1['points'] if winner == 1 else t2['points']}  ⬆",
                            inline=False)
                        embed.add_field(name=f'ZP:\t+{points1 if winner == 1 else points2}', value='\u200B',
                                        inline=False)
                        embed.add_field(name='\u200B', value='\u200B')
                        embed.add_field(name='💀 LOSER 💀',
                                        value=battle_instance['username1'] if winner == 2 else battle_instance[
                                            'username2'], inline=False)
                        loser_p = points1 if winner == 2 else points2
                        embed.add_field(
                            name=f"{t1['tier'] if winner == 2 else t2['tier']} {'🤡 Rank Down `⬇` 🤡' if (new_rank1 if winner == 2 else new_rank2) is not None else ''}",
                            value=f"{t1['points'] if winner == 2 else t2['points']} {'⬇' if loser_p > 0 else '⬆'}",
                            inline=False)
                        embed.add_field(name=f'ZP:\t{"-" if loser_p > 0 else "+"}{abs(loser_p)}', value='\u200B',
                                        inline=False)
                        await reaction.message.reply(embed=embed)
                except Exception as e:
                    logging.error(f"ERROR during friendly/ranked battle: {e}\n{traceback.format_exc()}")
                finally:
                    del config.battle_dict[_id]
                    config.ongoing_battles.remove(user.id)
                    config.ongoing_battles.remove(battle_instance["challenger"])
    elif reaction.emoji == "✅" and config.battle_royale_started:
        user_data = db_query.get_owned(user.id)
        if user_data is None:
            return
        else:
            if user_data is None or len(user_data['zerpmons']) == 0 or len(
                    user_data['trainer_cards']) == 0 or user.id in config.ongoing_battles:
                return
            else:
                if user.id not in [i['id'] for i in config.battle_royale_participants]:
                    config.battle_royale_participants.append({'id': user.id, 'username': user.mention})


# Reaction Tracker


# Autocomplete functions

@mission_trainer.on_autocomplete("trainer_name")
@trainer_deck.on_autocomplete("trainer_name")
async def trainer_autocomplete(interaction: nextcord.Interaction, item: str):
    # Determine the choices for the trainer_name option based on a condition
    user_owned = db_query.get_owned(interaction.user.id)
    cards = {k: v for k, v in user_owned['trainer_cards'].items() if item.lower() in v['name'].lower()}
    choices = {}
    if (len(cards)) == 0:
        pass
    else:
        for k, v in cards.items():
            if len(choices) == 25:
                break
            choices[v['name']] = k
    await interaction.response.send_autocomplete(choices)


@battle_deck.on_autocomplete("zerpmon_name")
@mission_deck.on_autocomplete("zerpmon_name")
async def mission_autocomplete(interaction: nextcord.Interaction, item: str):
    # Determine the choices for the trainer_name option based on a condition
    user_owned = db_query.get_owned(interaction.user.id)
    cards = {k: v for k, v in user_owned['zerpmons'].items() if item.lower() in v['name'].lower()}
    choices = {}
    if (len(cards)) == 0:
        pass
    else:
        for k, v in cards.items():
            if len(choices) == 25:
                break
            choices[v['name']] = k
    await interaction.response.send_autocomplete(choices)


# Autocomplete functions

client.run(config.BOT_TOKEN)
