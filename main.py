import asyncio
import concurrent
import json
import logging
import random
import threading
import time
import traceback
from collections import Counter
from typing import Optional, Literal
import nextcord
from nextcord import SlashOption, ButtonStyle
from nextcord.ui import Button, View
import config
from nextcord.ext import commands, tasks
import xumm_functions
import xrpl_functions
import db_query
from utils import battle_function, nft_holding_updater, xrpl_ws, db_cleaner, checks, callback, reset_alert, \
    auction_functions
from xrpl.utils import xrp_to_drops

from utils.autocomplete_functions import zerpmon_autocomplete, equipment_autocomplete
from utils.callback import wager_battle_r_callback

intents = nextcord.Intents.all()
client = commands.AutoShardedBot(command_prefix="/", intents=intents)

logging.basicConfig(filename='logfile_wrapper.log', level=logging.ERROR,
                    format='%(asctime)s %(levelname)s %(module)s %(funcName)s %(message)s %(lineno)d')

deck_options = []


def start_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()


@tasks.loop(seconds=10)
async def check_auction():
    print("checking auctions")
    aucs = auction_functions.get_auctions()
    if len(aucs) == 0:
        return
    for auc in aucs:
        auc_channel = await client.fetch_channel(auc["channelid"])
        print(f"checking {auc['name']}")
        time_left = auc["end_time"] - int(time.time())
        if time_left <= 0:
            auc_msg = await auc_channel.fetch_message(auc["msgid"])
            await auc_msg.edit(
                content="Auction has ended!\n\n**Winner:** " + f"<@{auc['bids_track'][-1]['bidder']}>" + "\n**Bid:** " + str(
                    auc["bids_track"][-1]["bid"]) + " " + auc["currency"])
            # await auc_channel.send("Congratulations, " + f"<@{auc['bids_track'][-1]['bidder']}>" + "!")
            embed = nextcord.Embed(title=f"{auc['name']} Auction Ended",
                                   description=f"Congratulations, <@{auc['bids_track'][-1]['bidder']}>! You won the auction for {auc['name']} at {auc['bids_track'][-1]['bid']} {auc['currency']}!",
                                   color=0x00ff00)
            nftData = xrpl_functions.get_nft_metadata_by_id(auc["nft_id"])["metadata"]
            image = nftData["image"]
            image = image.replace("ipfs://", "https://cloudflare-ipfs.com/ipfs/")
            embed.set_image(url=image)
            await auc_channel.send(embed=embed,
                                   content=f"<@{auc['bids_track'][-1]['bidder']}> congratulations!\n<@&{1135412428163788921}>")
            uAddress = db_query.get_owned(auc['bids_track'][-1]['bidder'])["address"]
            auction_functions.update_to_be_claimed(auc['name'], auc['bids_track'][-1]['bidder'], uAddress,
                                                   auction_functions.get_auction_by_name(auc['name'])["nft_id"],
                                                   auc["currency"], auc["bids_track"][-1]["bid"])
            auction_functions.delete_auction(auc["name"])
        pv_ann = auc["announces"]  # type
        if time_left <= 600 and time_left > 180 and pv_ann[0] == False:
            await auc_channel.send(f"Only 10 minutes left in the auction!\n<@&{1135412428163788921}>")
            pv_ann[0] = True
        elif time_left <= 180 and time_left > 60 and pv_ann[1] == False:
            await auc_channel.send(f"Only 3 minutes left in the auction!\n<@&{1135412428163788921}>")
            pv_ann[1] = True
        elif time_left <= 60 and time_left > 10 and pv_ann[2] == False:
            await auc_channel.send(f"Only 1 minute left in the auction!\n<@&{1135412428163788921}>")
            pv_ann[2] = True
        elif time_left <= 10 and time_left > 0:
            await auc_channel.send(f"Final countdown! Auction ends in 10 seconds!\n<@&{1135412428163788921}>")
            while True:
                await asyncio.sleep(2)
                # get the latest time left
                auc = auction_functions.get_auction_by_name(auc["name"])
                time_left = auc["end_time"] - int(time.time())
                if time_left <= 10 and time_left > 0:
                    await auc_channel.send("Auction ends in " + str(time_left) + " seconds!")
                else:
                    break
        auction_functions.update_auction_announces(auc["name"], pv_ann)


# create a new event loop
new_loop = asyncio.new_event_loop()

# start a new thread to run the event loop
t = threading.Thread(target=start_loop, args=(new_loop,))
t.start()

new_loop.call_soon_threadsafe(new_loop.create_task, xrpl_ws.main())


async def updater():
    await asyncio.create_task(nft_holding_updater.update_nft_holdings(client))
    pass


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
    for guild in client.guilds:
        print(guild.name)
    config.gym_main_reset = db_query.get_gym_reset()
    if not check_auction.is_running():
        check_auction.start()


@client.event
async def on_disconnect():
    print('Bot disconnected from Discord.')


@client.event
async def on_resumed():
    print('Bot resumed connection with Discord.')
    if not check_auction.is_running():
        check_auction.start()


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
                "equipments": {},
                "battle_deck": {'0': {}, '1': {}, '2': {}, '3': {}, '4': {}},
            }

            if not good_status:
                # In case the account isn't active or XRP server is down
                await interaction.send(f"**Sorry, encountered an Error!**", ephemeral=True)
                return

            for nft in nfts:

                if nft["Issuer"] == config.ISSUER["Trainer"]:

                    metadata = xrpl_functions.get_nft_metadata(nft['URI'])
                    serial = nft["nft_serial"]
                    if "Zerpmon Trainers" in metadata['description']:
                        # Add to MongoDB here
                        user_obj["trainer_cards"][serial] = {"name": metadata['name'],
                                                             "image": metadata['image'],
                                                             "attributes": metadata['attributes'],
                                                             "token_id": nft["NFTokenID"],
                                                             }

                if nft["Issuer"] == config.ISSUER["Zerpmon"]:
                    metadata = xrpl_functions.get_nft_metadata(nft['URI'])
                    serial = nft["nft_serial"]
                    if "Zerpmon " in metadata['description']:
                        # Add to MongoDB here
                        user_obj["zerpmons"][serial] = {"name": metadata['name'],
                                                        "image": metadata['image'],
                                                        "attributes": metadata['attributes'],
                                                        "token_id": nft["NFTokenID"],
                                                        }
                if nft["Issuer"] == config.ISSUER["Equipment"]:
                    metadata = xrpl_functions.get_nft_metadata(nft['URI'])
                    serial = nft["nft_serial"]
                    if "Zerpmon Equipment" in metadata['description']:
                        # Add to MongoDB here
                        user_obj["equipments"][serial] = {"name": metadata['name'],
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
    _b_num = 0 if 'battle' not in owned_nfts else owned_nfts['battle']['num']
    embed2 = CustomEmbed(title=f"YOUR **ZERPMON** HOLDINGS:\n",
                         color=0xff5252,
                         )
    embed2.add_field(name=f"Daily **Missions** left: **{10 - _b_num}**\n\n", value='\u200B', inline=False)
    for serial, nft in owned_nfts['trainer_cards'].items():
        if len(embed.fields) >= 10:
            break
        my_button = f"https://xrp.cafe/nft/{nft['token_id']}"
        nft_type = ', '.join([i['value'] for i in nft['attributes'] if i['trait_type'] == 'Nature'])

        embed.add_field(
            name=f"#{serial}  **{nft['name']}** ({nft_type})",
            value=f'[view]({my_button})', inline=False)

    # embed.add_field(
    #     name=f"----------------------------------",
    #     value='\u200B', inline=False)

    async def show_callback(interaction: nextcord.Interaction, items, start=0, return_embed=False):
        embed2 = CustomEmbed(
            title=f"YOUR **ZERPMON** HOLDINGS {'(Page #' + str(start // 15 + 1) + ')' if start >= 15 else ''}:\n",
            color=0xff5252,
        )
        view = View()
        for serial, nft in items:
            if len(embed2.fields) >= 15 and len(items) > 15:
                button = Button(label="Show more", style=ButtonStyle.blurple)
                view.add_item(button)
                view.timeout = 300
                button.callback = lambda i: show_callback(i, sorted_dict[start + 15:], start=start + 15)
                break
            lvl, xp, w_candy, g_candy, l_candy = db_query.get_lvl_xp(nft['name'], get_candies=True)

            my_button = f"https://xrp.cafe/nft/{nft['token_id']}"
            nft_type = ', '.join([i['value'] for i in nft['attributes'] if i['trait_type'] == 'Type'])
            active = "🟢" if 'active_t' not in nft or nft['active_t'] < time.time() else "🔴"
            embed2.add_field(
                name=f"{active}    #{serial}  **{nft['name']}** ({nft_type})",
                value=f'> White Candy: **{w_candy[1]}**\n'
                      f'> Gold Candy: **{g_candy}**\n'
                # f'> Liquorice: **{l_candy}**\n'
                      f'> Level: **{lvl}**\n'
                      f'> XP: **{xp}/{w_candy[0]}**\n'
                      f'> [view]({my_button})', inline=False)
        if return_embed:
            return embed2, view
        else:
            await interaction.send(embeds=[embed2], ephemeral=True, view=view)

    sorted_dict = [(k, v) for k, v in sorted(owned_nfts['zerpmons'].items())]
    embed2, view = await show_callback(interaction, sorted_dict, start=0, return_embed=True)

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

    await msg.edit(content="FOUND", embeds=[embed, embed2], view=view)


@client.slash_command(name="show_equipment", description="Show owned Zerpmon Equipments")
async def show_equipment(interaction: nextcord.Interaction):
    execute_before_command(interaction)
    await interaction.response.defer(ephemeral=True)
    owned_nfts = db_query.get_owned(interaction.user.id)
    embed3 = CustomEmbed(title=f"YOUR **ZERPMON** EQUIPMENT HOLDINGS:\n",
                         color=0x962071,
                         )
    eqs = sorted(list(owned_nfts['equipments'].values()), key=lambda k: k['name'])
    name_values = [obj['name'] for obj in eqs]
    counter = Counter(name_values)
    for i, nft in enumerate(eqs):
        if len(embed3.fields) > 24:
            break
        my_button = f"https://xrp.cafe/nft/{nft['token_id']}"
        my_button2 = None
        count = counter[nft['name']]
        if count > 1:
            second_item = [i for i in eqs if i['name'] == nft['name']][-1]
            my_button2 = f"https://xrp.cafe/nft/{second_item['token_id']}"
        nft_type = ', '.join([config.TYPE_MAPPING[i['value']] for i in nft['attributes'] if i['trait_type'] == 'Type'])

        embed3.add_field(
            name=f"#{i + 1}  **{nft['name']}** ({nft_type}) x{count}",
            value=f'[view]({my_button})' + (f'\n[view]({my_button2})' if my_button2 is not None else ''), inline=False)
    await interaction.edit_original_message(content="FOUND", embeds=[embed3])


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
    user_owned_nfts = {'data': db_query.get_owned(user_id), 'user': interaction.user.name}
    u_flair = f' | {user_owned_nfts["data"].get("flair", [])[0]}' if len(
        user_owned_nfts["data"].get("flair", [])) > 0 else ''
    user_owned_nfts['user'] += u_flair
    user_mention = interaction.user.mention + u_flair

    opponent_owned_nfts = {'data': db_query.get_owned(opponent.id), 'user': opponent.name}
    o_flair = f' | {opponent_owned_nfts["data"].get("flair", [])[0]}' if len(
        opponent_owned_nfts["data"].get("flair", [])) > 0 else ''
    opponent_owned_nfts['user'] += o_flair
    oppo_mention = opponent.mention + o_flair

    proceed = await checks.check_battle(user_id, opponent, user_owned_nfts, opponent_owned_nfts, interaction,
                                        battle_nickname='friendly')
    if not proceed:
        return
        #  Proceed with the challenge if check success
    await interaction.send("Battle conditions met", ephemeral=True)
    config.ongoing_battles.append(user_id)
    config.ongoing_battles.append(opponent.id)
    try:
        msg = await interaction.channel.send(
            f"**{type}v{type}** Friendly **battle** challenge to {oppo_mention} by {user_mention}. Click the **swords** to accept!")
        await msg.add_reaction("⚔")
        config.battle_dict[msg.id] = {
            "type": 'friendly',
            "challenger": user_id,
            "username1": user_mention,
            "challenged": opponent.id,
            "username2": oppo_mention,
            "active": False,
            "channel_id": interaction.channel_id,
            "timeout": time.time() + 60,
            'battle_type': type,
        }

        # Sleep for a while and notify timeout
        await asyncio.sleep(60)
        if msg.id in config.battle_dict and config.battle_dict[msg.id]['active'] == False:
            del config.battle_dict[msg.id]
            await msg.edit(
                f"Timed out! <t:{int(time.time())}:R>\nInfo:challenge to {oppo_mention} by {user_mention}")
            await msg.add_reaction("❌")
            config.ongoing_battles.remove(user_id)
            config.ongoing_battles.remove(opponent.id)
    except Exception as e:
        logging.error(f'ERROR in battle: {traceback.format_exc()}')
        config.ongoing_battles.remove(user_id)
        config.ongoing_battles.remove(opponent.id)


@client.slash_command(name="mission",
                      description="PvE / Solo Combat missions for Zerpmon holders",
                      )
async def mission(interaction: nextcord.Interaction):
    execute_before_command(interaction)
    user_id = interaction.user.id

    user_owned_nfts = {'data': db_query.get_owned(user_id), 'user': interaction.user.name}
    u_flair = f' | {user_owned_nfts["data"].get("flair", [])[0]}' if len(
        user_owned_nfts["data"].get("flair", [])) > 0 else ''
    user_owned_nfts['user'] += u_flair
    user_mention = interaction.user.mention + u_flair

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


@gift.subcommand(description="Gift mission refill potion")
async def mission_refill(interaction: nextcord.Interaction, qty: int,
                         user: Optional[nextcord.Member] = SlashOption(required=True)):
    # msg = await interaction.send(f"Searching...")
    execute_before_command(interaction)
    await callback.gift_callback(interaction, qty, user, 'mission_potion', 'Mission Refill Potion',
                                 db_query.add_mission_potion)


@gift.subcommand(description="Gift revive all potion")
async def revive_potion(interaction: nextcord.Interaction, qty: int,
                        user: Optional[nextcord.Member] = SlashOption(required=True)):
    # msg = await interaction.send(f"Searching...")
    execute_before_command(interaction)
    await callback.gift_callback(interaction, qty, user, 'revive_potion', 'Revive All Potion',
                                 db_query.add_revive_potion)


@gift.subcommand(name='white_candy', description="Gift White Power Candy")
async def revive_potion(interaction: nextcord.Interaction, qty: int,
                        user: Optional[nextcord.Member] = SlashOption(required=True)):
    # msg = await interaction.send(f"Searching...")
    execute_before_command(interaction)
    await callback.gift_callback(interaction, qty, user, 'white_candy', 'White Power Candy',
                                 db_query.add_white_candy)


@gift.subcommand(name='gold_candy', description="Gift Gold Power Candy")
async def revive_potion(interaction: nextcord.Interaction, qty: int,
                        user: Optional[nextcord.Member] = SlashOption(required=True)):
    # msg = await interaction.send(f"Searching...")
    execute_before_command(interaction)
    await callback.gift_callback(interaction, qty, user, 'gold_candy', 'Gold Power Candy',
                                 db_query.add_gold_candy)


@gift.subcommand(name='liquorice', description="Gift Golden Liquorice")
async def revive_potion(interaction: nextcord.Interaction, qty: int,
                        user: Optional[nextcord.Member] = SlashOption(required=True)):
    # msg = await interaction.send(f"Searching...")
    execute_before_command(interaction)
    await callback.gift_callback(interaction, qty, user, 'lvl_candy', 'Golden Liquorice',
                                 db_query.add_lvl_candy)


@gift.subcommand(name='gym_refill', description="Gift Gym Refill")
async def revive_potion(interaction: nextcord.Interaction, qty: int,
                        user: Optional[nextcord.Member] = SlashOption(required=True)):
    # msg = await interaction.send(f"Searching...")
    execute_before_command(interaction)
    await callback.gift_callback(interaction, qty, user, 'gym_refill', 'Gym Refill',
                                 db_query.add_gym_refill_potion)


@client.slash_command(name="add",
                      description="Set Zerpmon (for missions or battles)",
                      )
async def add(interaction: nextcord.Interaction):
    # ...
    pass


@add.subcommand(name='battle_zone', description="Set your Battle Zone")
async def set_battle_zone(interaction: nextcord.Interaction, zone: str = SlashOption("zone"),
                          ):
    execute_before_command(interaction)
    user = interaction.user
    user_obj = db_query.get_owned(user.id)
    if user_obj is None or len(user_obj.get('bg', [])) == 0:
        await interaction.send(
            f"Sorry, you don't own any **Battle Zone**",
            ephemeral=True)
        return

    db_query.set_user_bg(user_obj, zone)
    await interaction.send(
        f"**Success**",
        ephemeral=True)


@add.subcommand(name='name_flair', description="Set your Name Flair")
async def set_flair(interaction: nextcord.Interaction, flair: str = SlashOption("flair"),
                    ):
    execute_before_command(interaction)
    user = interaction.user
    user_obj = db_query.get_owned(user.id)
    if user_obj is None or len(user_obj.get('flair', [])) == 0:
        await interaction.send(
            f"Sorry, you don't own any **Name Flair**",
            ephemeral=True)
        return

    db_query.set_user_flair(user_obj, flair)
    await interaction.send(
        f"**Success**",
        ephemeral=True)


@add.subcommand(name='equipment', description="Set your Equipment on specific Battle decks")
async def set_equipment(interaction: nextcord.Interaction,
                        deck_type: str = SlashOption(
                            name="deck_type",
                            choices={"Gym": 'gym_deck', "Battle": 'battle_deck'},
                        ),
                        deck_number: str = SlashOption(
                            name="deck_number",
                            choices={"1st": '0', "2nd": '1', "3rd": '2', "4th": '3', "5th": '4'},
                        ),
                        eq1: str = SlashOption("1st", autocomplete_callback=equipment_autocomplete, required=False),
                        eq2: str = SlashOption("2nd", autocomplete_callback=equipment_autocomplete, required=False),
                        eq3: str = SlashOption("3rd", autocomplete_callback=equipment_autocomplete, required=False),
                        eq4: str = SlashOption("4th", autocomplete_callback=equipment_autocomplete, required=False),
                        eq5: str = SlashOption("5th", autocomplete_callback=equipment_autocomplete, required=False),
                        ):
    execute_before_command(interaction)
    user = interaction.user
    user_obj = db_query.get_owned(user.id)
    eqs = [eq1, eq2, eq3, eq4, eq5]

    if deck_type not in user_obj or (
            len(user_obj[deck_type]) == 0 or (
            deck_number in user_obj[deck_type] and len(user_obj[deck_type][deck_number]) == 0)):
        await interaction.send(
            f"Sorry, your can't add **Equipment** to an empty deck.",
            ephemeral=True)
        return
    else:
        user1_z = []
        i = 0
        try:
            del user_obj[deck_type][deck_number]['trainer']
        except:
            pass
        while len(user1_z) != len(user_obj[deck_type][deck_number]):
            try:
                user1_z.append(user_obj['zerpmons'][user_obj[deck_type][deck_number][str(i)]])
            except:
                user1_z.append(None)
            i += 1
        all_types = []
        [all_types.append(k['attributes']) for k in user1_z if k is not None]
        print(eqs, all_types)
        for eq_i, equipment in enumerate(eqs):
            if equipment == '' or equipment is None:
                eqs[eq_i] = None
                continue
            if user_obj is None or len(user_obj['equipments'].get(equipment, {})) == 0:
                await interaction.send(
                    f"Sorry, you don't own this **Equipment**",
                    ephemeral=True)
                return
            if all_types[eq_i] is None:
                await interaction.send(
                    f"Sorry, you can't set **Equipment** to an empty slot.\n"
                    f"You don't have a Zerpmon at **{eq_i + 1}** position",
                    ephemeral=True)
                return
            zerp_types = [i['value'] for i in all_types[eq_i] if i['trait_type'] == 'Type']
            for item in user_obj['equipments'][equipment]['attributes']:
                if item['trait_type'] == 'Type':
                    if item['value'] not in zerp_types:
                        await interaction.send(
                            f"Sorry, {config.TYPE_MAPPING[item['value']]}**{item['value']}** type equipment doesn't match **{' ,'.join(zerp_types)}** type **Zerpmon**",
                            ephemeral=True)
                        return
        db_query.set_equipment_on(user_obj['discord_id'], eqs, deck_type, deck_number)
        await interaction.send(
            f"**Success**",
            ephemeral=True)


@add.subcommand(name='equipment_mission', description="Set Zerpmon Equipment for Solo Missions")
async def equipment_mission(interaction: nextcord.Interaction,
                       eq1: str = SlashOption("1st", autocomplete_callback=equipment_autocomplete, required=False),
                       eq2: str = SlashOption("2nd", autocomplete_callback=equipment_autocomplete, required=False),
                       eq3: str = SlashOption("3rd", autocomplete_callback=equipment_autocomplete, required=False),
                       eq4: str = SlashOption("4th", autocomplete_callback=equipment_autocomplete, required=False),
                       eq5: str = SlashOption("5th", autocomplete_callback=equipment_autocomplete, required=False),
                       eq6: str = SlashOption("6th", autocomplete_callback=equipment_autocomplete, required=False),
                       eq7: str = SlashOption("7th", autocomplete_callback=equipment_autocomplete, required=False),
                       eq8: str = SlashOption("8th", autocomplete_callback=equipment_autocomplete, required=False),
                       eq9: str = SlashOption("9th", autocomplete_callback=equipment_autocomplete, required=False),
                       eq10: str = SlashOption("10th", autocomplete_callback=equipment_autocomplete, required=False),
                       eq11: str = SlashOption("11th", autocomplete_callback=equipment_autocomplete, required=False),
                       eq12: str = SlashOption("12th", autocomplete_callback=equipment_autocomplete, required=False),
                       eq13: str = SlashOption("13th", autocomplete_callback=equipment_autocomplete, required=False),
                       eq14: str = SlashOption("14th", autocomplete_callback=equipment_autocomplete, required=False),
                       eq15: str = SlashOption("15th", autocomplete_callback=equipment_autocomplete, required=False),
                       eq16: str = SlashOption("16th", autocomplete_callback=equipment_autocomplete, required=False),
                       eq17: str = SlashOption("17th", autocomplete_callback=equipment_autocomplete, required=False),
                       eq18: str = SlashOption("18th", autocomplete_callback=equipment_autocomplete, required=False),
                       eq19: str = SlashOption("19th", autocomplete_callback=equipment_autocomplete, required=False),
                       eq20: str = SlashOption("20th", autocomplete_callback=equipment_autocomplete, required=False),
                       ):
    execute_before_command(interaction)
    user = interaction.user
    user_obj = db_query.get_owned(user.id)
    eqs = [eq1, eq2, eq3, eq4, eq5, eq6, eq7, eq8, eq9, eq10, eq11, eq12, eq13, eq14, eq15, eq16, eq17, eq18, eq19, eq20]

    if user_obj is None or (len(user_obj.get('mission_deck', {})) == 0):
        await interaction.send(
            f"Sorry, your can't add **Equipment** to an empty deck.",
            ephemeral=True)
        return
    else:
        user1_z = []
        i = 0
        while len(user1_z) != len(user_obj['mission_deck']):
            try:
                user1_z.append(user_obj['zerpmons'][user_obj['mission_deck'][str(i)]])
            except:
                user1_z.append(None)
            i += 1
        all_types = []
        [all_types.append(k['attributes']) for k in user1_z if k is not None]
        print(eqs, all_types)
        for eq_i, equipment in enumerate(eqs):
            if equipment == '' or equipment is None:
                eqs[eq_i] = None
                continue
            if user_obj is None or len(user_obj['equipments'].get(equipment, {})) == 0:
                await interaction.send(
                    f"Sorry, you don't own this **Equipment**",
                    ephemeral=True)
                return
            if all_types[eq_i] is None:
                await interaction.send(
                    f"Sorry, you can't set **Equipment** to an empty slot.\n"
                    f"You don't have a Zerpmon at **{eq_i + 1}** position",
                    ephemeral=True)
                return
            zerp_types = [i['value'] for i in all_types[eq_i] if i['trait_type'] == 'Type']
            for item in user_obj['equipments'][equipment]['attributes']:
                if item['trait_type'] == 'Type':
                    if item['value'] not in zerp_types:
                        await interaction.send(
                            f"Sorry, {config.TYPE_MAPPING[item['value']]}**{item['value']}** type equipment doesn't match **{' ,'.join(zerp_types)}** type **Zerpmon**",
                            ephemeral=True)
                        return
        db_query.set_equipment_on(user_obj['discord_id'], eqs, 'mission_deck', None)
        await interaction.send(
            f"**Success**",
            ephemeral=True)


@add.subcommand(description="Set Zerpmon for Solo Missions")
async def mission_deck(interaction: nextcord.Interaction,
                       zerpmon_name1: str = SlashOption("1st", autocomplete_callback=zerpmon_autocomplete,
                                                        required=False, default=''),
                       zerpmon_name2: str = SlashOption("2nd", autocomplete_callback=zerpmon_autocomplete,
                                                        required=False, default=''),
                       zerpmon_name3: str = SlashOption("3rd", autocomplete_callback=zerpmon_autocomplete,
                                                        required=False, default=''),
                       zerpmon_name4: str = SlashOption("4th", autocomplete_callback=zerpmon_autocomplete,
                                                        required=False, default=''),
                       zerpmon_name5: str = SlashOption("5th", autocomplete_callback=zerpmon_autocomplete,
                                                        required=False, default=''),
                       zerpmon_name6: str = SlashOption("6th", autocomplete_callback=zerpmon_autocomplete,
                                                        required=False, default=''),
                       zerpmon_name7: str = SlashOption("7th", autocomplete_callback=zerpmon_autocomplete,
                                                        required=False, default=''),
                       zerpmon_name8: str = SlashOption("8th", autocomplete_callback=zerpmon_autocomplete,
                                                        required=False, default=''),
                       zerpmon_name9: str = SlashOption("9th", autocomplete_callback=zerpmon_autocomplete,
                                                        required=False, default=''),
                       zerpmon_name10: str = SlashOption("10th", autocomplete_callback=zerpmon_autocomplete,
                                                         required=False, default=''),
                       zerpmon_name11: str = SlashOption("11th", autocomplete_callback=zerpmon_autocomplete,
                                                         required=False, default=''),
                       zerpmon_name12: str = SlashOption("12th", autocomplete_callback=zerpmon_autocomplete,
                                                         required=False, default=''),
                       zerpmon_name13: str = SlashOption("13th", autocomplete_callback=zerpmon_autocomplete,
                                                         required=False, default=''),
                       zerpmon_name14: str = SlashOption("14th", autocomplete_callback=zerpmon_autocomplete,
                                                         required=False, default=''),
                       zerpmon_name15: str = SlashOption("15th", autocomplete_callback=zerpmon_autocomplete,
                                                         required=False, default=''),
                       zerpmon_name16: str = SlashOption("16th", autocomplete_callback=zerpmon_autocomplete,
                                                         required=False, default=''),
                       zerpmon_name17: str = SlashOption("17th", autocomplete_callback=zerpmon_autocomplete,
                                                         required=False, default=''),
                       zerpmon_name18: str = SlashOption("18th", autocomplete_callback=zerpmon_autocomplete,
                                                         required=False, default=''),
                       zerpmon_name19: str = SlashOption("19th", autocomplete_callback=zerpmon_autocomplete,
                                                         required=False, default=''),

                       zerpmon_name20: str = SlashOption("20th", autocomplete_callback=zerpmon_autocomplete,
                                                         required=False, default=''),
                       ):
    """
    Deal with 1v1 Zerpmon deck
    """
    execute_before_command(interaction)
    user = interaction.user

    user_owned_nfts = {'data': db_query.get_owned(user.id), 'user': user.name}
    # Sanity checks
    zerpmon_options = [zerpmon_name1, zerpmon_name2, zerpmon_name3, zerpmon_name4, zerpmon_name5, zerpmon_name6,
                       zerpmon_name7, zerpmon_name8, zerpmon_name9, zerpmon_name10, zerpmon_name11, zerpmon_name12,
                       zerpmon_name13, zerpmon_name14, zerpmon_name15, zerpmon_name16, zerpmon_name17, zerpmon_name18,
                       zerpmon_name19, zerpmon_name20]
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
        for zerpmon_name in zerpmon_options:
            if zerpmon_name != '' and zerpmon_name not in [i for i in
                                                           list(owned_nfts['data']['zerpmons'].keys())]:
                await interaction.send(
                    f"**Failed**, please recheck the ID/Name or make sure you hold this Zerpmon",
                    ephemeral=True)
                return
    new_deck = {}
    for i, zerpmon_name in enumerate(zerpmon_options):
        if zerpmon_name != '' and zerpmon_name is not None and zerpmon_name not in list(new_deck.values()):
            new_deck[str(i)] = zerpmon_name
    # await interaction.send(
    #     f"**Adding to deck...**",
    #     ephemeral=True)
    saved = db_query.update_mission_deck(new_deck, user.id)
    if not saved:
        await interaction.send(
            f"**Failed**, please recheck the ID or make sure you hold this Zerpmon",
            ephemeral=True)
    else:
        await interaction.send(
            f"**Success**",
            ephemeral=True)


@add.subcommand(description="Add Zerpmon to a specific Battle Deck (max 5)")
async def battle_deck(interaction: nextcord.Interaction,
                      deck_type: str = SlashOption(
                          name="deck_type",
                          choices={"Gym": 'True', "Battle": 'False'},
                      ),
                      deck_number: str = SlashOption(
                          name="deck_number",
                          choices={"1st": '0', "2nd": '1', "3rd": '2', "4th": '3', "5th": '4'},
                      ),
                      trainer_name: str = SlashOption("trainer_name", required=False, default=''),
                      zerpmon_name1: str = SlashOption("1st", autocomplete_callback=zerpmon_autocomplete,
                                                       required=False, default=''),
                      zerpmon_name2: str = SlashOption("2nd", autocomplete_callback=zerpmon_autocomplete,
                                                       required=False, default=''),
                      zerpmon_name3: str = SlashOption("3rd", autocomplete_callback=zerpmon_autocomplete,
                                                       required=False, default=''),
                      zerpmon_name4: str = SlashOption("4th", autocomplete_callback=zerpmon_autocomplete,
                                                       required=False, default=''),
                      zerpmon_name5: str = SlashOption("5th", autocomplete_callback=zerpmon_autocomplete,
                                                       required=False, default=''),
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
        for zerpmon_name in [zerpmon_name1, zerpmon_name2, zerpmon_name3, zerpmon_name4, zerpmon_name5]:
            if zerpmon_name != '' and zerpmon_name not in [i for i in
                                                           list(owned_nfts['data']['zerpmons'].keys())]:
                await interaction.send(
                    f"**Failed**, please recheck the ID/Name or make sure you hold these Zerpmon",
                    ephemeral=True)
                return
        if trainer_name != '' and trainer_name not in [i for i in
                                                       list(owned_nfts['data']['trainer_cards'].keys())]:
            await interaction.send(
                f"**Failed**, please recheck the ID/Name or make sure you hold this Trainer Card",
                ephemeral=True)
            return False
    new_deck = {}
    if trainer_name != '' and trainer_name is not None:
        new_deck['trainer'] = trainer_name
    for i, zerpmon_name in enumerate([zerpmon_name1, zerpmon_name2, zerpmon_name3, zerpmon_name4, zerpmon_name5]):
        if zerpmon_name != '' and zerpmon_name is not None and zerpmon_name not in list(new_deck.values()):
            new_deck[str(i)] = zerpmon_name
    print(new_deck)
    # await interaction.send(
    #     f"**Adding to deck...**",
    #     ephemeral=True)
    if deck_type == 'True':
        saved = db_query.update_gym_deck(str(deck_number), new_deck, user.id)
    else:
        saved = db_query.update_battle_deck(str(deck_number), new_deck, user.id)
    if not saved:
        await interaction.send(
            f"**Failed**, please recheck the ID or make sure you hold these Zerpmon",
            ephemeral=True)
    else:
        await interaction.send(
            f"**Success**",
            ephemeral=True)


@add.subcommand(name="default_deck", description="Set Default Battle Deck")
async def default_deck(interaction: nextcord.Interaction,
                       deck_type: str = SlashOption(
                           name="deck_type",
                           choices={"Gym": 'True', "Battle": 'False'},
                       ),
                       deck_number: str = SlashOption(
                           name="deck_number",
                           choices={"1st": '0', "2nd": '1', "3rd": '2', '4th': '3', '5th': '4'},
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
    saved = db_query.set_default_deck(str(deck_number), user.id, gym=True if deck_type == 'True' else False)
    if saved:
        await interaction.send(
            f"**Success**",
            ephemeral=True)


@client.slash_command(name="clear_deck",
                      description="Clear decks",
                      )
async def clear_deck(interaction: nextcord.Interaction):
    # ...
    pass


@clear_deck.subcommand(name="mission", description="Clear mission deck")
async def clear_mission_deck(interaction: nextcord.Interaction):
    execute_before_command(interaction)
    user = interaction.user

    user_owned_nfts = db_query.get_owned(user.id)
    if user_owned_nfts is None:
        await interaction.send("Sorry, you haven't verified your wallet yet!")
        return
    # await interaction.send(
    #     f"**Adding to deck...**",
    #     ephemeral=True)
    saved = db_query.clear_mission_deck(user.id)
    if not saved:
        await interaction.send(
            f"**Failed**",
            ephemeral=True)
    else:
        await interaction.send(
            f"**Success**",
            ephemeral=True)


@clear_deck.subcommand(name="battle_deck", description="Clear battle deck")
async def clear_battle_deck(interaction: nextcord.Interaction,
                            deck_type: str = SlashOption(
                                name="deck_type",
                                choices={"Gym": 'Gym', "Battle": 'Battle'},
                            ),
                            deck_number: str = SlashOption(
                                name="deck_number",
                                choices={"1st": '0', "2nd": '1', "3rd": '2', '4th': '3', '5th': '4'},
                            ),
                            ):
    execute_before_command(interaction)
    user = interaction.user

    user_owned_nfts = db_query.get_owned(user.id)
    if user_owned_nfts is None:
        await interaction.send("Sorry, you haven't verified your wallet yet!")
        return
    # await interaction.send(
    #     f"**Adding to deck...**",
    #     ephemeral=True)
    saved = db_query.clear_battle_deck(deck_no=deck_number, user_id=user.id, gym=True if deck_type == 'Gym' else False)
    if not saved:
        await interaction.send(
            f"**Failed**",
            ephemeral=True)
    else:
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
            eqs = owned_nfts['equipment_decks']['mission_deck']
            for place, serial in sorted(deck.items(), key=lambda x: int(x[0])):
                nft = owned_nfts['zerpmons'][serial]
                lvl, xp, xp_req, _r, _m = db_query.get_lvl_xp(nft['name'])
                # zerpmon = db_query.get_zerpmon(nft['name'])
                my_button = f"https://xrp.cafe/nft/{nft['token_id']}"
                nft_type = ', '.join([i['value'] for i in nft['attributes'] if i['trait_type'] == 'Type'])
                active = "🟢" if 'active_t' not in nft or nft['active_t'] < time.time() else "🔴"
                eq_name = owned_nfts['equipments'][eqs[place]]['name'] if eqs[place] in owned_nfts[
                    'equipments'] else None
                embed.add_field(
                    name=f"{active}    #{serial}  **{nft['name']}** ({nft_type}) {' - ' + eq_name if eq_name is not None else ''}",
                    value=f'> Level: **{lvl}**\n'
                          f'> XP: **{xp}/{xp_req}**\n', inline=False)
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
        embed2 = checks.get_deck_embed('battle', owned_nfts)
        embeds.append(embed2)
    if 'gym_deck' not in owned_nfts:
        pass
    else:
        embed3 = checks.get_deck_embed('gym', owned_nfts)
        embeds.append(embed3)
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


@use.subcommand(name="gym_refill", description="Use Gym Refill to reset failed gyms for the day")
async def use_gym_refill(interaction: nextcord.Interaction):
    execute_before_command(interaction)
    """
            Deal with Gym refill
            """
    res = await callback.use_gym_refill_callback(interaction)


@use.subcommand(name="power_candy_white",
                description="Use Power Candy (White) to ⬆ damage of White moves by 2% (1 Zerpmon)")
async def use_power_candy_white(interaction: nextcord.Interaction):
    execute_before_command(interaction)
    """
            Deal with Power Candy (White)
            """
    res = await callback.use_candy_callback(interaction, label='white')


@use.subcommand(name="power_candy_gold",
                description="Use Power Candy (Gold) to ⬆ damage of Gold moves by 2% (1 Zerpmon)")
async def use_power_candy_gold(interaction: nextcord.Interaction):
    execute_before_command(interaction)
    """
            Deal with Power Candy (Gold)
            """
    res = await callback.use_candy_callback(interaction, label='gold')


@use.subcommand(name="golden_liquorice",
                description="Use Golden Liquorice ⬆ the level of the Zerpmon that it is used on by 1")
async def use_golden_liquorice(interaction: nextcord.Interaction):
    execute_before_command(interaction)
    """
            Deal with Golden Liquorice
            """
    res = await callback.use_candy_callback(interaction, label='lvl')


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

    # Sanity checks
    if quantity <= 0:
        await interaction.send(
            f"Sorry, the quantity can't be less than 1",
            ephemeral=True)
        return

    await callback.purchase_callback(interaction, config.POTION[0], quantity)


@buy.subcommand(description="Purchase Mission Refill Potion using XRP (10 Missions)")
async def mission_refill(interaction: nextcord.Interaction, quantity: int):
    execute_before_command(interaction)

    # Sanity checks
    if quantity <= 0:
        await interaction.send(
            f"Sorry, the quantity can't be less than 1",
            ephemeral=True)
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
        lvl, xp, w_candy, g_candy, l_candy = db_query.get_lvl_xp(zerpmon['name'], get_candies=True)
        embed = CustomEmbed(title=f"**{zerpmon['name']}**:\n",
                            color=0xff5252,
                            )
        my_button = f"https://xrp.cafe/nft/{zerpmon['nft_id']}"
        nft_type = ', '.join([i['value'] for i in zerpmon['attributes'] if i['trait_type'] == 'Type'])

        embed.add_field(
            name=f"**{nft_type}**",
            value=f'           [view]({my_button})', inline=False)

        embed.add_field(
            name=f"**White Candy 🍬: {w_candy[1]}**",
            value=f"\u200B", inline=True)
        embed.add_field(
            name=f"**Gold Candy 🍭: {g_candy}**",
            value=f"\u200B", inline=False)
        # embed.add_field(
        #     name=f"**Liquorice 🍵: {l_candy}**",
        #     value=f"\u200B", inline=True)
        embed.add_field(
            name=f"**Level:**",
            value=f"**{lvl}/30**", inline=True)
        embed.add_field(
            name=f"**XP:**",
            value=f"**{xp}/{w_candy[0]}**", inline=True)

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
              reward: str = SlashOption(
                  name="reward",
                  choices={"XRP": 'XRP', "ZRP": 'ZRP'},
              ),
              opponent: Optional[nextcord.Member] = SlashOption(required=True),
              type: int = SlashOption(
                  name="picker",
                  choices={"1v1": 1, "2v2": 2, "3v3": 3, "4v4": 4, "5v5": 5},
              ),
              ):
    execute_before_command(interaction)
    user_id = interaction.user.id
    # Sanity checks
    await interaction.response.defer(ephemeral=True)
    channel_clean = battle_function.check_battle_happening(interaction.channel_id)
    if not channel_clean:
        await interaction.edit_original_message(
            content=f"Please wait, one battle is already taking place in this channel.")
        return

    user_owned_nfts = {'data': db_query.get_owned(user_id), 'user': interaction.user.name}
    u_flair = f' | {user_owned_nfts["data"].get("flair", [])[0]}' if len(
        user_owned_nfts["data"].get("flair", [])) > 0 else ''
    user_owned_nfts['user'] += u_flair
    user_mention = interaction.user.mention + u_flair

    opponent_owned_nfts = {'data': db_query.get_owned(opponent.id), 'user': opponent.name}
    o_flair = f' | {opponent_owned_nfts["data"].get("flair", [])[0]}' if len(
        opponent_owned_nfts["data"].get("flair", [])) > 0 else ''
    opponent_owned_nfts['user'] += o_flair
    oppo_mention = opponent.mention + o_flair

    print(opponent)

    # print([(k, v) for k, v in owned_nfts['zerpmons'].items()])

    # Sanity checks

    if user_id == opponent.id:
        await interaction.edit_original_message(content="You want to battle yourself 🥲, sorry that's not allowed.")
        return

    proceed = await checks.check_wager_entry(interaction, [user_owned_nfts, opponent_owned_nfts])
    if not proceed:
        return

    #  Proceed with the challenge if check success

    embed = CustomEmbed(title=f"Battle conditions met **{type}v{type}**", color=0x01f39d,
                        description=f'Please send over the required `{amount} {reward}` to Bot Wallet\n'
                                    f'{user_mention}\n'
                                    f'{oppo_mention}\n')
    embed.set_footer(text='Note: Amount will get distributed to the Winner.\n'
                          f'If battle timed out {reward} will be automatically returned within a few minutes')

    async def button_callback(_i: nextcord.Interaction, amount):
        if _i.user.id in [user_id, opponent.id]:
            await _i.send(content="Generating transaction QR code...", ephemeral=True)
            user_address = user_owned_nfts['data']['address']

            if reward == 'XRP':
                uuid, url, href = await xumm_functions.gen_txn_url(config.WAGER_ADDR, user_address, amount * 10 ** 6)
            else:
                uuid, url, href = await xumm_functions.gen_zrp_txn_url(config.WAGER_ADDR, user_address, amount)
            embed = CustomEmbed(color=0x01f39d,
                                title=f"Please sign the transaction using this QR code or click here.",
                                url=href)

            embed.set_image(url=url)

            await _i.send(embed=embed, ephemeral=True, )

    button = Button(label=f"SEND {reward}", style=ButtonStyle.green)
    view = View()
    view.add_item(button)
    view.timeout = 120
    button.callback = lambda _i: button_callback(_i, amount)

    if user_id in config.ongoing_battles or opponent.id in config.ongoing_battles:
        await interaction.edit_original_message(
            content="Please wait, one battle is already taking place for either you or your Opponent.",
        )

        return
    msg = await interaction.channel.send(embed=embed, view=view)

    config.ongoing_battles.append(user_id)
    config.ongoing_battles.append(opponent.id)

    config.wager_battles[msg.id] = {
        'type': 'wager',
        "challenger": user_id,
        "username1": user_mention,
        "challenged": opponent.id,
        "username2": oppo_mention,
        "active": True,
        "channel_id": interaction.channel_id,
        "timeout": time.time() + 120,
    }

    await asyncio.sleep(20)
    # Sleep for a while and notify timeout
    send_amount = xrpl_ws.send_txn if reward == 'XRP' else xrpl_ws.send_zrp
    try:
        user_sent, u_msg_sent = False, False
        opponent_sent, o_msg_sent = False, False
        for i in range(12):
            user_sent, opponent_sent = await xrpl_ws.check_amount_sent(amount, user_owned_nfts['data']['address'],
                                                                       opponent_owned_nfts['data']['address'],
                                                                       reward=reward)
            if user_sent and not u_msg_sent:
                embed.add_field(name=f'{user_mention} ✅', value='\u200B')
                await msg.edit(embed=embed)
                u_msg_sent = True
            if opponent_sent and not o_msg_sent:
                embed.add_field(name=f'{oppo_mention} ✅', value='\u200B')
                await msg.edit(embed=embed)
                o_msg_sent = True
            if user_sent and opponent_sent:
                winner = await battle_function.proceed_battle(msg, config.wager_battles[msg.id], type,
                                                              battle_name=f'Wager Battle ({reward})')
                user_sent, opponent_sent = False, False
                if winner == 1:
                    await msg.reply(f'Sending transaction for **`{amount * 2} {reward}`** to {user_mention}')
                    saved = await send_amount(user_owned_nfts['data']['address'],
                                              amount * 2, 'wager')
                else:
                    await msg.reply(f'Sending transaction for **`{amount * 2} {reward}`** to {oppo_mention}')
                    saved = await send_amount(opponent_owned_nfts['data']['address'],
                                              amount * 2, 'wager')

                if not saved:
                    await msg.reply(
                        f"**Failed**, something went wrong while sending the Txn")

                else:
                    await msg.reply(
                        f"**Successfully** sent `{amount * 2}` {reward}")
                    wager_obj = config.wager_senders if reward == 'XRP' else config.wager_zrp_senders

                    del wager_obj[user_owned_nfts['data']['address']]
                    del wager_obj[opponent_owned_nfts['data']['address']]
                break
            await asyncio.sleep(10)

        if user_sent or opponent_sent:
            await msg.reply(
                f"Preparing to return {reward} to {oppo_mention if opponent_sent else user_mention}.")
        # If users didn't send the wager
        for addr in config.wager_senders.copy():
            if addr in [user_owned_nfts['data']['address'], opponent_owned_nfts['data']['address']]:
                await send_amount(addr, config.wager_senders[addr], 'wager')

                if reward == 'XRP':
                    del config.wager_senders[addr]
                else:
                    del config.wager_zrp_senders[addr]

    except Exception as e:
        logging.error(f"ERROR during wager {reward} battle: {e}\n{traceback.format_exc()}")
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

    await interaction.response.defer(ephemeral=True)
    if user_id in config.ongoing_battles or opponent.id in config.ongoing_battles:
        await interaction.edit_original_message(
            content="Please wait, one battle is already taking place for either you or your Opponent.", )

        return

    channel_clean = battle_function.check_battle_happening(interaction.channel_id)
    if not channel_clean:
        await interaction.edit_original_message(
            content=f"Please wait, one battle is already taking place in this channel.", )

        return

    user_owned_nfts = {'data': db_query.get_owned(user_id), 'user': interaction.user.name}
    u_flair = f' | {user_owned_nfts["data"].get("flair", [])[0]}' if len(
        user_owned_nfts["data"].get("flair", [])) > 0 else ''
    user_owned_nfts['user'] += u_flair
    user_mention = interaction.user.mention + u_flair

    opponent_owned_nfts = {'data': db_query.get_owned(opponent.id), 'user': opponent.name}
    o_flair = f' | {opponent_owned_nfts["data"].get("flair", [])[0]}' if len(
        opponent_owned_nfts["data"].get("flair", [])) > 0 else ''
    opponent_owned_nfts['user'] += o_flair
    oppo_mention = opponent.mention + o_flair

    print(opponent)
    # print([(k, v) for k, v in owned_nfts['zerpmons'].items()])

    # Sanity checks

    if user_id == opponent.id:
        await interaction.edit_original_message(content=f"You want to battle yourself 🥲, sorry that's not allowed.")
        return

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

    embed2 = CustomEmbed(title=f'{user_mention} send NFT with ID: {your_nft_id}\n', color=0x01f39d)
    embed2.set_image(url1)
    embed2.add_field(name=f'{name1}', value='\u200B')

    embed3 = CustomEmbed(title=f'{oppo_mention} send NFT with ID: {opponent_nft_id}\n', color=0x01f39d)
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
        "username1": user_mention,
        "challenged": opponent.id,
        "username2": oppo_mention,
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
                embed.add_field(name=f'{user_mention} ✅', value='\u200B')
                await msg.edit(embeds=[embed, embed3])
                u_msg_sent = True
            if opponent_sent and not o_msg_sent:
                embed.add_field(name=f'{oppo_mention} ✅', value='\u200B')
                await msg.edit(embeds=[embed, embed2])
                o_msg_sent = True

            if user_sent and opponent_sent:
                winner = await battle_function.proceed_battle(msg, config.wager_battles[msg.id], type,
                                                              battle_name='Wager Battle (NFT)')
                user_sent, opponent_sent = False, False
                if winner == 1:
                    await msg.reply(
                        f'Sending transaction for `{your_nft_id}` and `{opponent_nft_id}` to {user_mention}')
                    saved = await xrpl_ws.send_nft_tx(user_owned_nfts['data']['address'],
                                                      [your_nft_id, opponent_nft_id])
                else:
                    await msg.reply(
                        f'Sending transaction for `{your_nft_id}` and `{opponent_nft_id}` to {oppo_mention}')
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
                f"Preparing to return NFT to {user_mention}.")
        elif opponent_sent:
            await msg.reply(
                f"Preparing to return NFT to {oppo_mention}.")
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


@wager_battle.subcommand(name='battle_royale',
                         description="Battle Royale by waging equal amounts of XRP (Winner takes all)")
async def battle_royale_wager(interaction: nextcord.Interaction, amount: int,
                              reward: str = SlashOption(
                                  name="reward",
                                  choices={"XRP": 'XRP', "ZRP": 'ZRP'},
                              ),
                              ):
    execute_before_command(interaction)
    await interaction.response.defer(ephemeral=True)
    if config.battle_royale_started or len(config.battle_royale_participants) > 0:
        await interaction.edit_original_message(content="Please wait another Battle Royale is already in progress.")
        return
    channel_clean = battle_function.check_battle_happening(interaction.channel_id)
    if not channel_clean:
        await interaction.edit_original_message(
            content="Please wait another Battle is already taking place in this channel.")
        return

    config.battle_royale_started = True

    button = Button(label=f"SEND {reward}", style=ButtonStyle.green)
    view = View()
    view.add_item(button)
    view.timeout = 300
    msg = await interaction.channel.send(
        embed=CustomEmbed(description="**Wager Battle Royale** started\n"
                                      f'Please send over the required `{amount} {reward}` to Bot Wallet to participate\n'
                                      f"Time left: `{5 * 60}s`", colour=0xf70776), view=view)

    async def wager_battle_r_callback(_i: nextcord.Interaction, amount):
        user_id = _i.user.id
        await _i.response.defer(ephemeral=True)
        if user_id in config.ongoing_battles:
            await _i.edit_original_message(
                content=f"Please wait, one battle is already taking place for either you or your Opponent.",
                view=View())

            return
        if user_id:
            user = db_query.get_owned(user_id)
            user_owned_nfts = {'data': db_query.get_owned(user_id), 'user': interaction.user.name}
            u_flair = f' | {user_owned_nfts["data"].get("flair", [])[0]}' if len(
                user_owned_nfts["data"].get("flair", [])) > 0 else ''
            user_owned_nfts['user'] += u_flair
            user_mention = _i.user.mention + u_flair
            proceed = await checks.check_wager_entry(_i, [user_owned_nfts])
            if not proceed:
                return
            await _i.edit_original_message(content="Generating transaction QR code...", view=View())
            user_address = user_owned_nfts["data"]['address']
            if reward == 'XRP':
                uuid, url, href = await xumm_functions.gen_txn_url(config.WAGER_ADDR, user_address, amount * 10 ** 6)
            else:
                uuid, url, href = await xumm_functions.gen_zrp_txn_url(config.WAGER_ADDR, user_address, amount)
            embed = CustomEmbed(color=0x01f39d,
                                title=f"Please sign the transaction using this QR code or click here.",
                                url=href)

            embed.set_image(url=url)

            await _i.edit_original_message(content='', embed=embed)
            addr = user['address']
            for i in range(15):
                wager_obj = config.wager_senders if reward == 'XRP' else config.wager_zrp_senders
                if addr in wager_obj:
                    if wager_obj[addr] == amount and user_id not in [i['id'] for i in
                                                                     config.battle_royale_participants]:
                        config.battle_royale_participants.append(
                            {'id': user_id, 'username': user_mention, 'address': addr})
                        del wager_obj[addr]
                        await _i.edit_original_message(content='', embed=CustomEmbed(title="**Success**",
                                                                                     description=f"Entered in Wager Battle Royale",
                                                                                     ))

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
                                              f'Please send over the required `{amount} {reward}` to Bot Wallet to participate\n'
                                              f"Time left: `{5 * 60 - ((i + 1) * 10)}s`\n"
                                              f"Participants: `{len(config.battle_royale_participants)}`\n"
                                              f"Winner gets: `{len(config.battle_royale_participants) * amount} {reward}`",
                                  colour=0xf70776))
        send_amount = xrpl_ws.send_txn if reward == 'XRP' else xrpl_ws.send_zrp
        if len(config.battle_royale_participants) <= 1:
            await msg.edit(embed=CustomEmbed(description=f"Battle **timed out** <t:{int(time.time())}:R>"), view=None)
            for user in config.battle_royale_participants:
                await send_amount(user["address"], amount, 'wager')

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
                                                              battle_instance['battle_type'],
                                                              battle_name='Wager Battle Royale')
                if winner == 1:
                    config.battle_royale_participants.append(random_ids[0])
                elif winner == 2:
                    config.battle_royale_participants.append(random_ids[1])
            except Exception as e:
                logging.error(f"ERROR during wager battle Royale: {e}\n{traceback.format_exc()}")
                await interaction.send(
                    f'Something went wrong during this match, returning both participants `{reward}`')
                for user in [random_ids[0], random_ids[1]]:
                    await send_amount(user["address"],
                                      amount, 'wager')

                    total_amount -= amount
            finally:
                config.ongoing_battles.remove(random_ids[0]['id'])
                config.ongoing_battles.remove(random_ids[1]['id'])
                del config.battle_dict[msg.id]

        await msg.channel.send(
            f"**CONGRATULATIONS** **{config.battle_royale_participants[0]['username']}** on winning the Wager Battle Royale!")

        await msg.reply(
            f'Sending transaction for **`{total_amount} {reward}`** to {config.battle_royale_participants[0]["username"]}')
        saved = await send_amount(config.battle_royale_participants[0]["address"], total_amount, 'wager')

        if not saved:
            await msg.reply(
                f"**Failed**, something went wrong while sending the Txn")

        else:
            await msg.reply(
                f"**Successfully** sent `{total_amount}` {reward}")
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
        rank = user['rank']['tier'] if 'rank' in user else 'Unranked'
        if i == 10:
            msg = '#{0:<4} {1:<25} W/L : {2:<2}/{3:<6} {4:<15}'.format(user['rank'], user['username'], user['pvp_win'],
                                                                       user['pvp_loss'], rank)
            embed.add_field(name=f'`{msg}`', value=f"\u200B", inline=False)
        else:
            msg = '#{0:<4} {1:<25} W/L : {2:<2}/{3:<6} {4:<15}'.format(i + 1, user['username'], user['pvp_win'],
                                                                       user['pvp_loss'], rank)
            embed.add_field(name=f'`{msg}`', value=f"\u200B", inline=False)

    await interaction.send(embed=embed, ephemeral=True)


@show_leaderboard.subcommand(description="Show Top purchasers Leaderboard of in-store items")
async def top_purchasers(interaction: nextcord.Interaction):
    execute_before_command(interaction)
    # ...
    users = db_query.get_top_purchasers(interaction.user.id)
    embed = CustomEmbed(color=0x01f39d,
                        title=f"TOP PURCHASERS LEADERBOARD")
    for i, user in enumerate(users):
        if i == 10:
            msg = '#{0:<4} {1:<25} XRP Spent : {2:<5} 🍶/🍹: {3:<2}/{4:<2}'.format(user['rank'], user['username'],
                                                                                   round(user['xrp_spent'], 2),
                                                                                   user[
                                                                                       'mission_purchase'] if 'mission_purchase' in user else 0,
                                                                                   user[
                                                                                       'revive_purchase'] if 'revive_purchase' in user else 0)
            embed.add_field(name=f'`{msg}`', value=f"\u200B", inline=False)
        else:
            msg = '#{0:<4} {1:<25} XRP Spent : {2:<5} 🍶/🍹: {3:<2}/{4:<2}'.format(i + 1, user['username'],
                                                                                   round(user['xrp_spent'], 2),
                                                                                   user[
                                                                                       'mission_purchase'] if 'mission_purchase' in user else 0,
                                                                                   user[
                                                                                       'revive_purchase'] if 'revive_purchase' in user else 0)
            embed.add_field(name=f'`{msg}`', value=f"\u200B", inline=False)

    await interaction.send(embed=embed, ephemeral=True)


@show_leaderboard.subcommand(name='gym', description="Show Gym Leaderboard")
async def gym_ld(interaction: nextcord.Interaction):
    execute_before_command(interaction)
    # ...
    users = db_query.get_gym_leaderboard(interaction.user.id)
    embed = CustomEmbed(color=0xa56cc1,
                        title=f"GYM LEADERBOARD")

    for i, user in enumerate(users):
        if str(interaction.user.id) == user['discord_id']:
            msg = '#{0:<4} {1:<25} TIER: {2:<20} GP : {3:>2}'.format(user['ranked'], user['username'],
                                                                     user['rank_title'],
                                                                     user['gym']['gp'])
            print(msg)
            embed.add_field(name=f'`{msg}`', value=f"\u200B", inline=False)
        else:
            msg = '#{0:<4} {1:<25} TIER: {2:<20} GP : {3:>2}'.format(user['ranked'], user['username'],
                                                                     user['rank_title'],
                                                                     user['gym']['gp'])
            embed.add_field(name=f'`{msg}`', value=f"\u200B", inline=False)

    await interaction.send(embed=embed, ephemeral=True)


@client.slash_command(name='battle_royale', description='Start Battle Royale -> 1 Zerpmon from each player ( max 50 )',
                      )
async def battle_royale(interaction: nextcord.Interaction,
                        reward: str = SlashOption(
                            required=True,
                            name="reward",
                            choices={"XRP": "XRP", "ZRP": "ZRP"}
                        ),
                        amount: int = SlashOption(required=True, min_value=0),
                        start_after: int = SlashOption(
                            name="start_after",
                            choices={"1 min": 1, "2 min": 2, "3 min": 3, "1 hour": 60, "4 hour": 240, "8 hour": 480, "12 hour": 720},
                        ), ):
    execute_before_command(interaction)
    await interaction.response.defer(ephemeral=True)
    user_address = db_query.get_owned(interaction.user.id).get('address', None)
    if user_address is None:
        await interaction.edit_original_message(
            content='Please verify your wallet before starting a Battle Royale.')
        return
    if config.battle_royale_started or len(config.battle_royale_participants) > 0:
        await interaction.edit_original_message(content="Please wait another Battle Royale is already in progress.")
        return
    channel_clean = battle_function.check_battle_happening(interaction.channel_id)
    if not channel_clean:
        await interaction.edit_original_message(
            content="Please wait another Battle is already taking place in this channel.")
        return

    button = Button(label=f"SEND {reward}", style=ButtonStyle.green)
    view = View()
    view.add_item(button)
    view.timeout = 300

    button.callback = lambda _i: wager_battle_r_callback(_i, amount, user_address, reward)
    addr = user_address
    if amount > 0:
        a_msg = await interaction.edit_original_message(content='',
                                                        embed=CustomEmbed(
                                                            description=f'Please send over the required `{amount} {reward}` to Bot Wallet to start\n'
                                                                        f"Time: <t:{int(time.time() + 300)}:R>",
                                                            colour=0xf70776), view=view)
        amount_sent = False
        wager_obj = config.wager_senders if reward == 'XRP' else config.wager_zrp_senders
        for i in range(15):
            if addr in wager_obj:
                if wager_obj[addr] == amount:
                    del wager_obj[addr]
                    amount_sent = True
                    await interaction.edit_original_message(embed=CustomEmbed(title="**Success**",
                                                                              ), view=View(), content='')
            if amount_sent:
                break
            await asyncio.sleep(20)
        if not amount_sent:
            await interaction.response.delete()
            raise ValueError("Amount not sent.")
    else:
        await interaction.edit_original_message(content='Conditions met')
    config.battle_royale_started = True
    t_str = f"`{start_after * 60}s`" if start_after < 4 else f"<t:{int(time.time()) + (start_after * 60)}:R>"
    msg = await interaction.channel.send(
        f"**Battle Royale** started. Click the **check mark** to enter!\nTime: {t_str}",
        embeds=[CustomEmbed(title=f"Reward Pot: {amount} {reward}")] if amount > 0 else [])
    await msg.add_reaction("✅")
    config.battle_royale_msg = msg.id
    if start_after < 4:
        for i in range(6 * start_after):
            await asyncio.sleep(10)
            if len(config.battle_royale_participants) >= 50:
                break
            await msg.edit(
                f"**Battle Royale** started. Click the **check mark** to enter!\nTime: `{start_after * 60 - ((i + 1) * 10)}s`")
    else:
        await asyncio.sleep(start_after * 60)

    send_amount = xrpl_ws.send_txn if reward == 'XRP' else xrpl_ws.send_zrp
    if len(config.battle_royale_participants) <= 1:
        await msg.edit(content=f"Battle **timed out** <t:{int(time.time())}:R>")
        config.battle_royale_participants = []
        config.battle_royale_started = False
        if amount > 0:
            await send_amount(user_address,
                              amount, 'wager')
        return

    try:
        config.battle_royale_started = False
        await msg.edit(content="Battle **beginning**")
        while len(config.battle_royale_participants) > 1:
            random_ids = random.sample(config.battle_royale_participants, 2)
            # Remove the selected players from the array
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
                                                              battle_instance['battle_type'],
                                                              battle_name='Battle Royale')
                if winner == 1:
                    config.battle_royale_participants.append(random_ids[0])
                elif winner == 2:
                    config.battle_royale_participants.append(random_ids[1])
            except Exception as e:
                logging.error(f"ERROR during friendly battle R: {e}\n{traceback.format_exc()}")
            finally:
                config.ongoing_battles.remove(random_ids[0]['id'])
                config.ongoing_battles.remove(random_ids[1]['id'])
                del config.battle_dict[msg.id]

        await msg.channel.send(
            f"**CONGRATULATIONS** **{config.battle_royale_participants[0]['username']}** on winning the Battle Royale!")
        if amount > 0:
            await msg.reply(
                f'Sending transaction for **`{amount} {reward}`** to {config.battle_royale_participants[0]["username"]}')
            saved = await send_amount(config.battle_royale_participants[0]["address"],
                                      amount, 'wager')
            if not saved:
                await msg.reply(
                    f"**Failed**, something went wrong while sending the Txn")

            else:
                await msg.reply(
                    f"**Successfully** sent `{amount}` {reward}")
    except Exception as e:
        logging.error(f'Error in battleR: {traceback.format_exc()}')
        if amount > 0:
            await send_amount(user_address,
                              amount, 'wager')
    finally:
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
    u_flair = f' | {user_owned_nfts.get("flair", [])[0]}' if len(
        user_owned_nfts.get("flair", [])) > 0 else ''
    user_mention = interaction.user.mention + u_flair

    opponent_owned_nfts = db_query.get_owned(opponent.id)
    o_flair = f' | {opponent_owned_nfts.get("flair", [])[0]}' if len(
        opponent_owned_nfts.get("flair", [])) > 0 else ''
    oppo_mention = opponent.mention + o_flair

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

    embed2 = CustomEmbed(description=f'{user_mention} send NFT with ID: {your_nft_id}\n', color=0x01f39d)
    embed2.set_image(url1)
    embed2.add_field(name=f'{name1}', value='\u200B')

    embed3 = CustomEmbed(description=f'{oppo_mention} send NFT with ID: {opponent_nft_id}\n', color=0x01f39d)
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
                embed.add_field(name=f'{user_mention} ✅', value='\u200B')
                await msg.edit(embeds=[embed, embed3])
                u_msg_sent = True
            if opponent_sent and not o_msg_sent:
                embed.add_field(name=f'{oppo_mention} ✅', value='\u200B')
                await msg.edit(embeds=[embed, embed2])
                o_msg_sent = True

            if user_sent and opponent_sent:
                user_sent, opponent_sent = False, False

                await msg.reply(
                    f'Sending transaction for `{your_nft_id}` to {oppo_mention} and `{opponent_nft_id}` to {user_mention}')
                saved1 = await xrpl_ws.send_nft_tx(user_owned_nfts['address'],
                                                   [opponent_nft_id])

                saved2 = await xrpl_ws.send_nft_tx(opponent_owned_nfts['address'],
                                                   [your_nft_id])
                if not (saved1 and saved2):
                    await msg.reply(
                        f"**Failed**, something went wrong while sending the Txn")

                else:
                    embed2 = CustomEmbed(description=f'**Successfully** sent `{your_nft_id}`\n',
                                         color=0x01f39d)
                    embed2.set_image(url1)
                    embed2.add_field(name=f'{name1}', value='\u200B')

                    embed3 = CustomEmbed(description=f'**Successfully** sent `{opponent_nft_id}`\n',
                                         color=0x01f39d)
                    embed3.set_image(url2)
                    embed3.add_field(name=f'{name2}', value='\u200B')
                    await msg.reply(
                        embeds=[embed2, embed3])
                    del config.wager_senders[user_owned_nfts['address']]
                    del config.wager_senders[opponent_owned_nfts['address']]
                break
            await asyncio.sleep(10)
        if user_sent:
            await msg.reply(
                f"Preparing to return NFT to {user_mention}.")
            saved1 = await xrpl_ws.send_nft_tx(user_owned_nfts['address'],
                                               [your_nft_id])
            del config.wager_senders[user_owned_nfts['address']]
        elif opponent_sent:
            await msg.reply(
                f"Preparing to return NFT to {oppo_mention}.")
            saved2 = await xrpl_ws.send_nft_tx(opponent_owned_nfts['address'],
                                               [opponent_nft_id])
            del config.wager_senders[opponent_owned_nfts['address']]

    except Exception as e:
        logging.error(f"ERROR during NFT Trade: {e}\n{traceback.format_exc()}")
    finally:
        await msg.edit(embed=CustomEmbed(title="Finished"), view=None)


@client.slash_command(name="trade_potion",
                      description="Trade potions (Mission Refill potion <-> Revive All potion)",
                      )
async def trade_potion(interaction: nextcord.Interaction, amount: int,
                       trade_type: int = SlashOption(
                           name="picker",
                           choices={"Give Mission Refill Potion get Revive All Potion": 1,
                                    "Give Revive All Potion get Mission Refill Potion": 2},
                       ),
                       trade_with: Optional[nextcord.Member] = SlashOption(required=True),
                       ):
    user = interaction.user
    if user.id == trade_with.id:
        await interaction.send(
            f"Please choose a valid member to Trade with.")
        return False
    user_owned_nfts = db_query.get_owned(user.id)
    u_flair = f' | {user_owned_nfts.get("flair", [])[0]}' if len(
        user_owned_nfts.get("flair", [])) > 0 else ''
    user_mention = interaction.user.mention + u_flair

    opponent_owned_nfts = db_query.get_owned(trade_with.id)
    o_flair = f' | {opponent_owned_nfts.get("flair", [])[0]}' if len(
        opponent_owned_nfts.get("flair", [])) > 0 else ''
    oppo_mention = trade_with.mention + o_flair
    potion_on_hold = False
    try:
        if trade_type == 1:
            if user_owned_nfts is None or user_owned_nfts['mission_potion'] < amount:
                await interaction.send(
                    f"Sorry you don't have {amount} Mission Refill Potion.")
                return False
            elif opponent_owned_nfts is None or opponent_owned_nfts['revive_potion'] < amount:
                await interaction.send(
                    f"Sorry {trade_with.name} doesn't have {amount} Revive All Potion.")
                return False
            else:
                # Put potions on hold os user doesn't spam
                db_query.add_mission_potion(user_owned_nfts['address'], -amount)
                potion_on_hold = True
                embed = CustomEmbed(title="Trade request",
                                    description=f'{oppo_mention}, {user_mention} wants to trade their {amount} Mission Refill Potion for your {amount} Revive All Potion\n',
                                    color=0x01f39d)
                embed.add_field(name="React with a ✅ if you agree to this Trade", value='\u200B')
                msg = await interaction.channel.send(embed=embed)

        elif trade_type == 2:
            if opponent_owned_nfts is None or opponent_owned_nfts['mission_potion'] < amount:
                await interaction.send(
                    f"Sorry {trade_with.name} doesn't have {amount} Mission Refill Potion.")
                return False
            elif user_owned_nfts is None or user_owned_nfts['revive_potion'] < amount:
                await interaction.send(
                    f"Sorry you don't have {amount} Revive All Potion.")
                return False
            else:
                # Put potions on hold os user doesn't spam
                db_query.add_revive_potion(user_owned_nfts['address'], -amount)
                potion_on_hold = True
                embed = CustomEmbed(title="Trade request",
                                    description=f'{oppo_mention}, {user_mention} wants to trade their {amount} Revive All Potion for your {amount} Mission Refill Potion\n',
                                    color=0x01f39d)
                embed.add_field(name="React with a ✅ if you agree to this Trade", value='\u200B')
                msg = await interaction.channel.send(embed=embed)
        await msg.add_reaction("✅")
        config.potion_trades[msg.id] = {
            "challenger": user.id,
            "username1": user_mention,
            "address1": user_owned_nfts['address'],
            "challenged": trade_with.id,
            "username2": oppo_mention,
            "address2": opponent_owned_nfts['address'],
            "active": False,
            "channel_id": interaction.channel_id,
            "timeout": time.time() + 60,
            "amount": amount,
            "trade_type": trade_type
        }
        await asyncio.sleep(60)
        if msg.id in config.potion_trades and config.potion_trades[msg.id]['active'] == False:
            del config.potion_trades[msg.id]
            await msg.edit(embeds=[CustomEmbed(title=f"Timed out!",
                                               description=f"<t:{int(time.time())}:R>\n**Info**: {oppo_mention}, {user_mention} wanted to trade their {amount} Revive All Potion for your {amount} Mission Refill Potion")])
            await msg.add_reaction("❌")
            if potion_on_hold:
                if trade_type == 1:
                    db_query.add_mission_potion(user_owned_nfts['address'], amount)
                elif trade_type == 2:
                    db_query.add_revive_potion(user_owned_nfts['address'], amount)
    except:
        if msg.id in config.potion_trades and config.potion_trades[msg.id]['active'] == False:
            del config.potion_trades[msg.id]
            if potion_on_hold:
                if trade_type == 1:
                    db_query.add_mission_potion(user_owned_nfts['address'], amount)
                elif trade_type == 2:
                    db_query.add_revive_potion(user_owned_nfts['address'], amount)


@client.slash_command(name="free",
                      description="free battles with rewards initiated by anyone",
                      )
async def free(interaction: nextcord.Interaction):
    pass


@free.subcommand(name='battle_royale', description="Battle Royale initiated using XRP by one person (Winner takes it)")
async def free_battle_royale(interaction: nextcord.Interaction, amount: int,
                             reward: str = SlashOption(
                                 name="reward",
                                 choices={"XRP": 'XRP', "ZRP": 'ZRP'},
                             ),
                             start_after: int = SlashOption(
                                 name="start_after",
                                 choices={"1 min": 1, "2 min": 2, "3 min": 3, "1 hour": 60, "4 hour": 240,
                                          "8 hour": 480, "12 hour": 720},
                             ), ):
    execute_before_command(interaction)
    user_id = interaction.user.id
    await interaction.response.defer(ephemeral=True)
    try:
        user_address = db_query.get_owned(interaction.user.id).get('address', None)
        if user_address is None:
            await interaction.edit_original_message(
                content='Please verify your wallet before starting a Battle Royale.')
            return
        all_p = []
        [all_p.extend(i) for k, i in config.free_battle_royale_p.items()]
        if user_id in [i['id'] for i in all_p]:
            await interaction.edit_original_message(
                content='Please wait you are already participating in another Battle Royale.',
            )
            return

        channel_clean = battle_function.check_battle_happening(interaction.channel_id)
        if not channel_clean:
            await interaction.edit_original_message(
                content="Please wait another Battle is already taking place in this channel.")
            return
        config.free_br_channels.append(interaction.channel_id)

        button = Button(label=f"SEND {reward}", style=ButtonStyle.green)
        view = View()
        view.add_item(button)
        view.timeout = 300

        button.callback = lambda _i: wager_battle_r_callback(_i, amount, user_address, reward)
        addr = user_address
        if amount > 0:
            a_msg = await interaction.send(
                embed=CustomEmbed(
                    description=f'Please send over the required `{amount} {reward}` to Bot Wallet to start\n'
                                f"Time: <t:{int(time.time() + 300)}:R>", colour=0xf70776), view=view,
                delete_after=300,
                ephemeral=True)
            amount_sent = False
            wager_obj = config.wager_senders if reward == 'XRP' else config.wager_zrp_senders
            for i in range(15):
                if addr in wager_obj:
                    if wager_obj[addr] == amount:
                        del wager_obj[addr]
                        amount_sent = True
                        await interaction.edit_original_message(embed=CustomEmbed(title="**Success**",
                                                                                  ), view=View(), content='')
                if amount_sent:
                    break
                await asyncio.sleep(20)
            if not amount_sent:
                await a_msg.delete()
                raise ValueError("Amount not sent.")
        else:
            await interaction.edit_original_message(content='Conditions met')
        t_str = f"`{start_after * 60}s`" if start_after < 4 else f"<t:{int(time.time()) + (start_after * 60)}:R>"
        msg = await interaction.channel.send(
            f"**Free For All Battle Royale - Use /wallet to register with Zerpmon Bot and then click the green checkmark ✅ to join!**\nTime: {t_str}\n",
            embeds=[CustomEmbed(title=f"Reward Pot: {amount} {reward}")] if amount > 0 else [])

        await msg.add_reaction("✅")
    except Exception as e:
        logging.error(f'Free Battle R error: {traceback.format_exc()}')
        config.free_br_channels.remove(interaction.channel_id)
        return

    try:
        config.free_battle_royale_p[msg.id] = []
        if start_after < 4:
            for i in range(6 * start_after):
                await asyncio.sleep(10)
                if len(config.free_battle_royale_p[msg.id]) >= 50:
                    break
                await msg.edit(
                    f"**Free For All Battle Royale - Use /wallet to register with Zerpmon Bot and then click the green checkmark ✅ to join!**\nTime: `{start_after * 60 - ((i + 1) * 10)}s`\n"
                )
        else:
            await asyncio.sleep(start_after * 60)
        send_amount = xrpl_ws.send_txn if reward == 'XRP' else xrpl_ws.send_zrp
        if len(config.free_battle_royale_p[msg.id]) <= 1:
            await msg.edit(embed=CustomEmbed(description=f"Battle **timed out** <t:{int(time.time())}:R>"), view=None)
            await msg.add_reaction("❌")
            if amount > 0:
                await send_amount(user_address,
                                  amount, 'wager')
            return
        zerp_embed = CustomEmbed(title=f"Reward Pot: {amount} {reward}" if amount > 0 else '',
                                 description="Battle **beginning!**")
        for i, user_obj in enumerate(config.free_battle_royale_p[msg.id].copy()):
            user_zerps = db_query.get_owned(user_obj['id'])['zerpmons']
            if len(user_zerps) > 0:
                zerp = random.choice(list(user_zerps.keys()))
                z_name = user_zerps[zerp]["name"]
            else:
                zerp = db_query.get_rand_zerpmon(level=1)
                z_name = zerp['name'] + ' (FTP)'
            user_obj['zerp'] = zerp
            config.free_battle_royale_p[msg.id][i] = user_obj
            zerp_embed.add_field(name='\u200B', value=f'{user_obj["username"]} draws **{z_name}**',
                                 inline=False)
        await msg.edit(embed=zerp_embed, view=None)
        total_amount = amount
        while len(config.free_battle_royale_p[msg.id]) > 1:
            random_ids = random.sample(config.free_battle_royale_p[msg.id], 2)
            # Remove the selected IDs from the array
            config.free_battle_royale_p[msg.id] = [id_ for id_ in config.free_battle_royale_p[msg.id] if
                                                   id_ not in random_ids]
            config.ongoing_battles.append(random_ids[0]['id'])
            config.ongoing_battles.append(random_ids[1]['id'])

            battle_instance = {
                "type": 'free_br',
                "challenger": random_ids[0]['id'],
                "z1": random_ids[0]['zerp'],
                "username1": random_ids[0]['username'],
                "challenged": random_ids[1]['id'],
                "z2": random_ids[1]['zerp'],
                "username2": random_ids[1]['username'],
                "active": True,
                "channel_id": interaction.channel_id,
                "timeout": time.time() + 60,
                'battle_type': 1,
            }
            config.battle_dict[msg.id] = battle_instance

            try:

                winner = await battle_function.proceed_battle(msg, battle_instance,
                                                              battle_instance['battle_type'],
                                                              battle_name='Free Battle Royale')
                if winner == 1:
                    config.free_battle_royale_p[msg.id].append(random_ids[0])
                elif winner == 2:
                    config.free_battle_royale_p[msg.id].append(random_ids[1])
            except Exception as e:
                logging.error(f"ERROR during friendly battle R: {e}\n{traceback.format_exc()}")
                await interaction.send(
                    f'Something went wrong during this match{", returning `" + reward + "`" if amount > 0 else ""}')
            finally:
                config.ongoing_battles.remove(random_ids[0]['id'])
                config.ongoing_battles.remove(random_ids[1]['id'])
                del config.battle_dict[msg.id]

        await msg.channel.send(embed=CustomEmbed(
            description=f"**CONGRATULATIONS** **{config.free_battle_royale_p[msg.id][0]['username']}** on winning the Battle Royale!\n"
                        f"Thanks for playing Zerpmon Battle Royale, if you would like to level-up, battle and earn {reward} with your very own Zerpmon, you can purchase one [here](https://xrp.cafe/collection/zerpmon)\n"
                        f"Learn more about Zerpmon [here](https://www.zerpmon.world/) and join the [Discord](https://discord.gg/TYZsTjDyRN) now!")
        )
        if amount > 0:
            await msg.reply(
                f'Sending transaction for **`{total_amount} {reward}`** to {config.free_battle_royale_p[msg.id][0]["username"]}')
            saved = await send_amount(config.free_battle_royale_p[msg.id][0]["address"],
                                      total_amount, 'wager')
            if not saved:
                await msg.reply(
                    f"**Failed**, something went wrong while sending the Txn")

            else:
                await msg.reply(
                    f"**Successfully** sent `{total_amount}` {reward}")
    finally:
        del config.free_battle_royale_p[msg.id]
        config.free_br_channels.remove(interaction.channel_id)


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
    if interaction.guild_id not in config.MAIN_GUILD:
        await interaction.send("Sorry, you can do Ranked Battles only in Official Server.")
        return
    user_owned_nfts = {'data': db_query.get_owned(user_id), 'user': interaction.user.name}
    u_flair = f' | {user_owned_nfts["data"].get("flair", [])[0]}' if len(
        user_owned_nfts["data"].get("flair", [])) > 0 else ''
    user_owned_nfts['user'] += u_flair
    user_mention = interaction.user.mention + u_flair

    opponent_owned_nfts = {'data': db_query.get_owned(opponent.id), 'user': opponent.name}
    o_flair = f' | {opponent_owned_nfts["data"].get("flair", [])[0]}' if len(
        opponent_owned_nfts["data"].get("flair", [])) > 0 else ''
    opponent_owned_nfts['user'] += o_flair
    oppo_mention = opponent.mention + o_flair
    proceed = await checks.check_battle(user_id, opponent, user_owned_nfts, opponent_owned_nfts, interaction,
                                        battle_nickname='Ranked')
    if not proceed:
        return
        #  Proceed with the challenge if check success

    await interaction.send("Ranked Battle conditions met", ephemeral=True)
    config.ongoing_battles.append(user_id)
    config.ongoing_battles.append(opponent.id)
    try:
        msg = await interaction.channel.send(
            f"**3v3** Ranked **battle** challenge to {oppo_mention} by {user_mention}. Click the **swords** to accept!")
        await msg.add_reaction("⚔")
        config.battle_dict[msg.id] = {
            "type": 'ranked',
            "challenger": user_id,
            "username1": user_mention,
            "challenged": opponent.id,
            "username2": oppo_mention,
            "active": False,
            "channel_id": interaction.channel_id,
            "timeout": time.time() + 60,
            'battle_type': 3,
        }

        # Sleep for a while and notify timeout
        await asyncio.sleep(60)
        if msg.id in config.battle_dict and config.battle_dict[msg.id]['active'] == False:
            del config.battle_dict[msg.id]
            await msg.edit(
                f"Timed out! <t:{int(time.time())}:R>\n**Info**: Challenge to {oppo_mention} by {user_mention}")
            await msg.add_reaction("❌")
            config.ongoing_battles.remove(user_id)
            config.ongoing_battles.remove(opponent.id)
    except Exception as e:
        logging.error(f"ERROR during friendly/ranked battle: {e}\n{traceback.format_exc()}")
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
            msg = '#{0:<4} {1:<25} TIER: {2:<20} ZP : {3:>2}'.format(user['ranked'], user['username'],
                                                                     user['rank']['tier'],
                                                                     user['rank']['points'])
            print(msg)
            embed.add_field(name=f'`{msg}`', value=f"\u200B", inline=False)
        else:
            msg = '#{0:<4} {1:<25} TIER: {2:<20} ZP : {3:>2}'.format(user['ranked'], user['username'],
                                                                     user['rank']['tier'],
                                                                     user['rank']['points'])
            embed.add_field(name=f'`{msg}`', value=f"\u200B", inline=False)

    await interaction.send(embed=embed, ephemeral=True)


# auction commands

@client.slash_command(name="auction", description="Create an auction")
@commands.has_permissions(administrator=True)
async def auction(interaction: nextcord.Interaction, nftid: str, price: int, duration: int,
                  duration_type: Literal["hours", "days"], currency: Literal["XRP", "ZRP"], quick: bool = False):
    await interaction.response.defer(ephemeral=True)
    nftid = nftid.strip()
    nftData = xrpl_functions.get_nft_metadata_by_id(nftid)
    if nftData is None:
        await interaction.edit_original_message(content=f"Could not find NFT with ID {nftid}")
        return
    if duration_type == "hours":
        duration = duration * 3600  # convert to seconds
    elif duration_type == "days":
        duration = duration * 86400  # convert to seconds
    else:
        await interaction.edit_original_message(content=f"Invalid duration type. Must be hours or days")
        return
    if quick:  # 15 min auction
        duration = 900
    nftData = nftData["metadata"]
    name = nftData["name"]
    allAuctionNames = auction_functions.get_auctions_names()
    if name in allAuctionNames:
        await interaction.edit_original_message(content=f"{name} is already up for auction!")
        return
    image = nftData["image"]
    curTime = int(time.time())
    # endTime = curTime + duration - 3000
    endTime = curTime + duration
    image = image.replace("ipfs://", "https://cloudflare-ipfs.com/ipfs/")
    print("Image: ", image)
    embed = nextcord.Embed(title=f"{name} is up for auction!",
                           description=f"{name} is up for auction, use /bid to bid on it!",
                           color=random.randint(0, 0xffffff))
    embed.set_image(url=image)
    embed.add_field(name="End Time", value=f"<t:{endTime}:R>")
    embed.add_field(name="Floor Price", value=f"{price} {currency}")
    await interaction.edit_original_message(content="created a new auction!")
    msg = await interaction.channel.send(embed=embed,
                                         content=f"<@&{1135412428163788921}> Gather up! It's time for an auction!")
    auction_functions.register_auction(nftid, price, duration, duration_type, name, endTime, currency, msg.id,
                                       msg.channel.id)
    # start a timer to end the auction
    # while True:
    #     # check if auction still exists
    #     if name not in auction_functions.get_auctions_names():
    #         break
    #     curTime = int(time.time())
    #     endTime = auction_functions.get_auction_by_name(name)["end_time"]
    #     if curTime >= endTime:
    #         break
    #     await asyncio.sleep(30)
    # # end the auction
    # highestBidder = auction_functions.get_highest_bidder(name)
    # if highestBidder is None:
    #     await interaction.channel.send(content=f"The auction for {name} has ended, but no one bid on it!")
    #     return
    # highestBid = auction_functions.get_highest_bid(name)
    # embed = nextcord.Embed(title=f"{name} auction has ended!",
    #                        description=f"{name} auction has ended, <@{highestBidder}> won it with a bid of {highestBid} {currency}!",
    #                        color=random.randint(0, 0xffffff))
    # embed.set_image(url=image)
    # embed.add_field(name="Floor Price", value=f"{price} {currency}")
    # embed.add_field(name="Winner", value=f"<@{highestBidder}>")
    # embed.add_field(name="Winning Bid", value=f"{highestBid} {currency}")
    # await interaction.channel.send(embed=embed)
    # uAddress = db_query.get_owned(highestBidder)["address"]
    # auction_functions.update_to_be_claimed(name, highestBidder, uAddress,
    #                                        auction_functions.get_auction_by_name(name)["nft_id"], currency, highestBid)
    # auction_functions.delete_auction(name)


@client.slash_command(name="bid", description="Bid on an auction")
async def bid(
        interaction: nextcord.Interaction,
        *,
        name: str,
        bid: int
):
    await interaction.response.defer(ephemeral=True)
    name = name.strip()
    if name not in auction_functions.get_auctions_names():
        await interaction.edit_original_message(content=f"Could not find auction with name {name}")
        return
    curTime = int(time.time())
    auc = auction_functions.get_auction_by_name(name)
    chan = interaction.guild.get_channel(auc["channelid"])
    if chan is None:
        await interaction.edit_original_message(content=f"Could not find auction with name {name}")
        return
    if interaction.channel.id != chan.id:
        await interaction.edit_original_message(content=f"You must bid in the same channel as the auction!<#{chan.id}>")
        return
    endTime = auc["end_time"]
    floor = auc["floor"]
    msgid = auc["msgid"]
    if bid < floor:
        await interaction.edit_original_message(content=f"Your bid must be higher than the floor price!")
        return
    if curTime >= endTime:
        await interaction.edit_original_message(content=f"Auction has ended!")
        return
    if bid <= auction_functions.get_highest_bid(name):
        await interaction.edit_original_message(content=f"Your bid must be higher than the current highest bid!")
        return
    # uAddress = db_query.get_owned(interaction.user.id)["address"]
    if interaction.user.id == 739375301578194944:
        uAddress = "rbKoFeFtQr2cRMK2jRwhgTa1US9KU6v4L"
    else:
        uAddress = db_query.get_owned(interaction.user.id)["address"]
    # if uAddress != "rbKoFeFtQr2cRMK2jRwhgTa1US9KU6v4L":
    if uAddress is None:
        await interaction.edit_original_message(
            content=f"Address not found :/. Please Link your account to bid on auctions!")
        return
    # balance = await xrpl_functions.get_xrp_balance(uAddress)
    if auc["currency"] == "XRP":
        balance = float(await xrpl_functions.get_xrp_balance(uAddress))
    else:
        balance = float(await xrpl_functions.get_zrp_balance(uAddress))
    print(balance)
    if uAddress == "rbKoFeFtQr2cRMK2jRwhgTa1US9KU6v4L":
        balance = 500
    balance = float(balance)
    if balance < bid:
        await interaction.edit_original_message(content=f"You do not have enough {auc['currency']} to bid that much!")
        return
    auction_functions.update_auction_bid(name, interaction.user.id, bid)
    await interaction.edit_original_message(content=f"Bid of {bid} {auc['currency']} placed on {name}!")
    embed = nextcord.Embed(title=f"{name} is up for auction!",
                           description=f"{name} is up for auction, use /bid to bid on it!",
                           color=random.randint(0, 0xffffff))
    image = xrpl_functions.get_nft_metadata_by_id(auc["nft_id"])["metadata"]["image"]
    image = image.replace("ipfs://", "https://cloudflare-ipfs.com/ipfs/")
    embed.set_image(url=image)
    embed.add_field(name="End Time", value=f"<t:{endTime + 60}:R>")
    embed.add_field(name="Floor Price", value=f"{floor} {auc['currency']}")
    embed.add_field(name="Highest Bid", value=f"{bid} {auc['currency']}")
    # await interaction.followup.edit_message(msgid, embed=embed)
    msg = await interaction.channel.fetch_message(msgid)
    await msg.edit(embed=embed)
    await interaction.channel.send(
        content=f"<@{interaction.user.id}> has placed a bid of {bid} {auc['currency']} on {name}!")

    # if time left for auction to end is less than 2 minutes, extend it by 1 minute
    diff = endTime - curTime
    if diff < 120:
        auction_functions.update_auction_endtime(name, endTime + 60)
        await interaction.channel.send(content=f"The timer for {name} has been extended by 1 minute!")
        # edit the embed
        embed = nextcord.Embed(title=f"{name} is up for auction!",
                               description=f"{name} is up for auction, use /bid to bid on it!",
                               color=random.randint(0, 0xffffff))
        image = xrpl_functions.get_nft_metadata_by_id(auc["nft_id"])["metadata"]["image"]
        image = image.replace("ipfs://", "https://cloudflare-ipfs.com/ipfs/")
        embed.set_image(url=image)
        embed.add_field(name="End Time", value=f"<t:{endTime + 60}:R>")
        embed.add_field(name="Floor Price", value=f"{floor} {auc['currency']}")
        embed.add_field(name="Highest Bid", value=f"{bid} {auc['currency']}")
        await interaction.followup.edit_message(msgid, embed=embed)


@client.slash_command(name="auctions", description="Get all auctions")
async def auctions(interaction: nextcord.Interaction):
    await interaction.response.defer(ephemeral=True)
    auctions = auction_functions.get_auctions()
    if len(auctions) == 0:
        await interaction.edit_original_message(content=f"There are no auctions currently!")
        return
    # put out name and floor price and end time
    embed = nextcord.Embed(title=f"Current Auctions", description=f"Here are all the current auctions!",
                           color=random.randint(0, 0xffffff))
    for auction in auctions:
        name = auction["name"]
        endTime = auction["end_time"]
        currency = auction["currency"]
        highestBid = auction_functions.get_highest_bid(name)
        if highestBid is None:
            highestBid = 0
        embed.add_field(name=name, value=f"Highest Bid: {highestBid} {currency}\nEnd Time: <t:{endTime}:R>")
    await interaction.edit_original_message(content=f"Here are all the current auctions!", embed=embed)


@client.slash_command(name="highestbid", description="Get the highest bid on an auction")
async def highestbid(interaction: nextcord.Interaction, *, name: str):
    await interaction.response.defer(ephemeral=True)
    name = name.strip()
    if name not in auction_functions.get_auctions_names():
        await interaction.edit_original_message(content=f"Could not find auction with name {name}")
        return
    highestBid = auction_functions.get_highest_bid(name)
    auctionn = auction_functions.get_auction_by_name(name)
    if highestBid is None:
        await interaction.edit_original_message(content=f"No one has bid on this auction yet!")
        return
    await interaction.edit_original_message(
        content=f"The highest bid on {name} is {highestBid} {auctionn['currency']} by <@{auction_functions.get_highest_bidder(name)}>!")


@client.slash_command(name="forceend", description="Force an auction to end")
@commands.has_permissions(administrator=True)
async def forceend(interaction: nextcord.Interaction, *, name: str, claimable: bool = True):
    await interaction.response.defer(ephemeral=True)
    name = name.strip()
    if name not in auction_functions.get_auctions_names():
        await interaction.edit_original_message(content=f"Could not find auction with name {name}")
        return
    if claimable == False:
        # delete auction without announcing winner
        auction_functions.delete_auction(name)
        await interaction.edit_original_message(content=f"The auction for {name} has been ended!")
        return
    highestBidder = auction_functions.get_highest_bidder(name)
    if highestBidder is None:
        await interaction.edit_original_message(content=f"The auction for {name} has ended, but no one bid on it!")
        auction_functions.delete_auction(name)
        return
    highestBid = auction_functions.get_highest_bid(name)
    currency = auction_functions.get_auction_by_name(name)["currency"]
    embed = nextcord.Embed(title=f"{name} auction has ended!",
                           description=f"{name} auction has ended, <@{highestBidder}> won it with a bid of {highestBid} {currency}!",
                           color=random.randint(0, 0xffffff))
    # embed.set_image(url=xrpl_functions.get_nft_metadata_by_id(auction_functions.get_auction_by_name(name)["nft_id"])["image"])
    image = xrpl_functions.get_nft_metadata_by_id(auction_functions.get_auction_by_name(name)["nft_id"])["metadata"][
        "image"]
    image = image.replace("ipfs://", "https://cloudflare-ipfs.com/ipfs/")
    embed.set_image(url=image)
    embed.add_field(name="Floor Price", value=f"{auction_functions.get_auction_by_name(name)['floor']} {currency}")
    embed.add_field(name="Winner", value=f"<@{highestBidder}>")
    embed.add_field(name="Winning Bid", value=f"{highestBid} XRP")
    await interaction.edit_original_message(
        content=f"{name} auction has ended, <@{highestBidder}> won it with a bid of {highestBid} {currency}!")
    await interaction.channel.send(embed=embed)
    # uAddress = db_query.get_owned(highestBidder)["address"]
    if highestBidder == 739375301578194944:
        uAddress = "rbKoFeFtQr2cRMK2jRwhgTa1US9KU6v4L"
    else:
        uAddress = db_query.get_owned(highestBidder)["address"]
    auction_functions.update_to_be_claimed(name, highestBidder, uAddress,
                                           auction_functions.get_auction_by_name(name)["nft_id"], currency, highestBid)
    auction_functions.delete_auction(name)


@client.slash_command(name="check-claims", description="Check if you have any claims")
async def check_claims(interaction: nextcord.Interaction):
    await interaction.response.defer(ephemeral=True)
    claims = auction_functions.get_to_be_claimed()
    if len(claims) == 0:
        await interaction.edit_original_message(content=f"You have no claims!")
        return
    uClaims = []
    for claim in claims:
        if claim["userid"] == interaction.user.id:
            uClaims.append(claim)
    if len(uClaims) == 0:
        await interaction.edit_original_message(content=f"You have no claims!")
        return
    embed = nextcord.Embed(title=f"Your Claims",
                           description=f"Here are all your claims!\nUse `/claim` + name of the nft to claim it!",
                           color=random.randint(0, 0xffffff))
    for claim in uClaims:
        embed.add_field(name="Claim",
                        value=f"You have a claim for {claim['price']} {claim['currency']} for the auction {claim['name']}!")
    await interaction.edit_original_message(
        content=f"Here are all your claims!\nUse `/claim` + name of the nft to claim it!", embed=embed)


@client.slash_command(name="claim", description="Claim an auction you won")
async def claim(interaction: nextcord.Interaction, *, name: str):
    await interaction.response.defer(ephemeral=True)
    name = name.strip()
    tbc = auction_functions.get_to_be_claimed_by_name(name)
    if tbc is None:
        await interaction.edit_original_message(content=f"Could not find claim with name {name}")
        return
    # if tbc["userid"] != interaction.user.id:
    #     await interaction.edit_original_message(content=f"You can't claim this!")
    #     return
    if tbc["currency"] == "XRP":
        offer, offerhash = await xrpl_ws.create_nft_offer('reward', tbc["nftid"], xrp_to_drops(int(tbc["price"])),
                                                          tbc["useraddress"])
        print(offer, offerhash)
        if offer:
            xumm_payload = {
                "txjson": {
                    "Account": tbc["useraddress"],
                    "TransactionType": "NFTokenAcceptOffer",
                    "NFTokenSellOffer": offerhash
                }
            }
            _, qr, deeplink = await xumm_functions.construct_xumm_payload(xumm_payload)
            # await interaction.edit_original_message(content=f"offer successfully created!\nCheck (xrp.cafe)[https://xrp.cafe/nft/{tbc['nftid']}] to claim your NFT!")
            embed = nextcord.Embed(title=f"Claim your NFT!",
                                   description=f"Click [here]({deeplink}) or scan the qr code to claim your NFT!",
                                   color=random.randint(0, 0xffffff))
            embed.set_image(url=qr)
            await interaction.edit_original_message(
                content=f"offer successfully created! Use xumm wallet to scan the qr code and accept the nft offer!",
                embed=embed)
            auction_functions.delete_to_be_claimed(name)
        else:
            await interaction.edit_original_message(
                content=f"Something went wrong!\nPlease try again later!\nIf this keeps happening, please contact an admin!")
    else:
        offer, offerhash = await xrpl_ws.create_nft_offer('reward', tbc["nftid"], tbc["price"], tbc["useraddress"],
                                                          tbc["currency"])
        xumm_payload = {
            "txjson": {
                "Account": tbc["useraddress"],
                "TransactionType": "NFTokenAcceptOffer",
                "NFTokenSellOffer": offerhash
            }
        }
        _, qr, deeplink = await xumm_functions.construct_xumm_payload(xumm_payload)
        if offer:
            # await interaction.edit_original_message(content=f"offer successfully created!\nCheck (xmart)[https://xmart.art] to claim your NFT! (login with xumm and go to your account offers!)")
            embed = nextcord.Embed(title=f"Claim your NFT!",
                                   description=f"Click [here]({deeplink}) or scan the qr code to claim your NFT!",
                                   color=random.randint(0, 0xffffff))
            embed.set_image(url=qr)
            await interaction.edit_original_message(
                content=f"offer successfully created! Use xumm wallet to scan the qr code and accept the nft offer, alternatively:\nCheck (xmart)[https://xmart.art] to claim your NFT! (login with xumm and go to your account offers!)",
                embed=embed)
            auction_functions.delete_to_be_claimed(name)
        else:
            await interaction.edit_original_message(
                content=f"Something went wrong!\nPlease try again later!\nIf this keeps happening, please contact an admin!")


@view_main.subcommand(name="gyms", description="Show Gyms")
async def view_gyms(interaction: nextcord.Interaction):
    execute_before_command(interaction)
    # ...
    embed = CustomEmbed(color=0x01f39d,
                        title=f"Gym Info")
    user_d = db_query.get_owned(interaction.user.id)
    won_list = []
    if user_d is not None:
        embed.add_field(name='GYMS COMPLETED ✅', value='\u200B', inline=False)
        if 'gym' not in user_d:
            user_d['gym'] = {
                'won': {}, 'active_t': 0, 'gp': 0
            }

        won_list = [[k, v['stage'], int(v['next_battle_t'])] for k, v in user_d['gym']['won'].items() if
                    v['lose_streak'] == 0]
        won_list = sorted(won_list, key=lambda x: x[0])
        lost_list = [[k, v['stage'], int(v['next_battle_t'])] for k, v in user_d['gym']['won'].items() if
                     [k, v['stage'], int(v['next_battle_t'])] not in won_list]
        lost_list = sorted(lost_list, key=lambda x: x[0])
        won_list.append(['', 0])
        won_list.extend(lost_list)

    not_played = [[k, 1, 0] for k in config.GYMS if k not in [i[0] for i in won_list]]
    not_played = sorted(not_played, key=lambda x: x[0])
    won_list.append(['x', 0])
    won_list.extend(not_played)
    for gym in won_list:
        print(gym)
        if gym[0] == '':
            embed.add_field(name='GYMS LOST 🚫', value='\u200B', inline=False)
            continue
        elif gym[0] == 'x':
            embed.add_field(name='GYMS NOT BATTLED', value='\u200B', inline=False)
            continue
        emj = config.TYPE_MAPPING[gym[0]]
        leader = db_query.get_gym_leader(gym[0])
        zerps = leader["zerpmons"]
        zerps = sorted(zerps, key=lambda i: i['name'])
        embed.add_field(
            name=f'{emj} {gym[0]} Gym {emj} (Stage {gym[1]}){f" - Reset <t:{gym[2]}:R>" if gym[2] > time.time() else ""}',
            value=f'> {zerps[0]["name"]}\n'
                  f'> {zerps[1]["name"]}\n'
                  f'> {zerps[2]["name"]}\n'
                  f'> {zerps[3]["name"]}\n'
                  f'> {zerps[4]["name"]}\n',
            inline=False)
    h, m, s = await checks.get_time_left_utc(1)
    main_ts = db_query.get_gym_reset()
    embed.add_field(name='\u200B', value=f'Won Gym reset: <t:{int(main_ts)}:R>', inline=False)
    embed.set_footer(icon_url=config.ICON_URL, text=f'Time left in Gym Leader Zerpmon Reset {h}h {m}m\n'
                                                    )
    await interaction.send(embed=embed, ephemeral=True)


@view_main.subcommand(name="battle_log", description="Show Battle logs")
async def view_logs(interaction: nextcord.Interaction):
    execute_before_command(interaction)
    # ...
    embed = CustomEmbed(color=0x01f39d,
                        title=f"Battle Log")
    log = db_query.get_battle_log(interaction.user.id)
    if log is None:
        await interaction.send(content="Sorry, you haven't played any matches.", ephemeral=True)
        return

    view = View()

    async def show_next_match(_i: nextcord.Interaction, match_obj, num):
        embed = CustomEmbed(color=0x01f39d,
                            title=f"Match {num} details")
        match_obj = match_obj[num]
        oppo = match_obj["opponent"]
        emj = '👑' if match_obj['won'] else '💀'
        ts = f'<t:{match_obj["ts"]}:R>' if 'ts' in match_obj else ''
        embed.add_field(name=f'{match_obj["battle_type"]} {ts}',
                        value=f'{emj}{interaction.user.mention}{emj} vs {oppo}' if oppo != 'Mission' else f'\u200B',
                        inline=False)
        embed.add_field(name=f'Result',
                        value=f'{emj}  **{"Victory" if emj == "👑" else "Defeat"}**  {emj}',
                        inline=False)
        match_d = match_obj['data']
        t1 = match_d['teamA']['trainer']['name'] if match_d['teamA']['trainer'] is not None else ''
        t2 = match_d['teamB']['trainer']['name'] if match_d['teamB']['trainer'] is not None else ''
        if oppo != 'Mission' and 'Free' not in match_obj['battle_type']:
            if t1 != '':
                href = f"https://xrp.cafe/nft/{xrpl_functions.get_nft_id_by_name(t1)}"
                embed.add_field(name=f'Trainers',
                                value=f'{t1} [view]({href})',
                                inline=True)
            if t1 != '' and t2 != '':
                embed.add_field(name=f'\u200B',
                                value=f'vs',
                                inline=True)
            if t2 != '':
                nft_id = xrpl_functions.get_nft_id_by_name(t2)
                href = f"https://xrp.cafe/nft/{nft_id}"
                embed.add_field(name=f'\u200B',
                                value=f'{t2} [view]({config.gym_links[t2] if nft_id is None else href})',
                                inline=True)
        embed.add_field(name='\u200B',
                        value='\u200B',
                        inline=False)
        user1_z = match_d['teamA']['zerpmons']
        user2_z = match_d['teamB']['zerpmons']
        while len(user1_z) != 0 and len(user2_z) != 0:
            _z1 = user1_z[0]
            _z2 = user2_z[0]
            href1 = f"https://xrp.cafe/nft/{xrpl_functions.get_nft_id_by_name(_z1['name'])}"
            href2 = f"https://xrp.cafe/nft/{xrpl_functions.get_nft_id_by_name(_z2['name'])}"
            _msg = '{0:<20} {1:<2} {2:>20}'.format(f'{_z1["name"]}', 'vs', f'{_z2["name"]}')
            blank_space = '{0:35}'.format(' ')
            href_msg = f'`    `[view]({href1})`{blank_space}`[view]({href2})'
            embed.add_field(name=f'{"☠️" if _z1["rounds"][0] == 0 else "🏆"}\t`{_msg}`',
                            value=f"{href_msg}"
                                  f"\nKnockout move: **{_z1['ko_move'] if _z1['rounds'][0] == 0 else _z2['ko_move']}**",
                            inline=False)
            if _z2['rounds'][0] == 0:
                _z1['rounds'].remove(1)
                user2_z = [i for i in user2_z if i['name'] != _z2['name']]
            else:
                _z2['rounds'].remove(1)
                user1_z = [i for i in user1_z if i['name'] != _z1['name']]

        await interaction.send(embed=embed, ephemeral=True
                               )

    pages = {1: '1️⃣', 2: '2️⃣', 3: '3️⃣', 4: '4️⃣', 5: '5️⃣', 6: '6️⃣', 7: '7️⃣', 8: '8️⃣', 9: '9️⃣', 10: '🔟'}

    for i, match in enumerate(log['matches']):

        button = Button(style=ButtonStyle.secondary, emoji=pages[i + 1])
        button.callback = lambda _i, key=i: show_next_match(_i, log['matches'], key)
        view.add_item(button)

        emj = '👑' if match['won'] else '💀'
        ts = f'<t:{match["ts"]}:R>' if 'ts' in match else ''
        oppo = match["opponent"]
        embed.add_field(name=f'Match #{i + 1} ({match["battle_type"]}) {ts}',
                        value=f'{emj}{interaction.user.mention}{emj} vs {oppo}' if oppo != 'Mission' else f'{emj}',
                        inline=False)
        match = match['data']
        t1 = match['teamA']['trainer']['name'] if match['teamA']['trainer'] is not None else ''
        t2 = match['teamB']['trainer']['name'] if match['teamB']['trainer'] is not None else ''
        if t1 == '' and t2 == '':
            msg = ''
        else:
            msg = '{0:<18} {1:<2} {2:>18}\n\n'.format(t1, 'vs' if t1 != '' and t2 != '' else '',
                                                      t2, ) if oppo != 'Mission' else ''

        if t1 == '' and t2 == '':
            for i in range(max([len(match['teamA']['zerpmons']), len(match['teamB']['zerpmons'])])):
                z1 = config.get_index_safely(match['teamA']['zerpmons'], i)
                z2 = config.get_index_safely(match['teamB']['zerpmons'], i)
                msg += '{0:<18} {1:<2} {2:>18}\n'.format(z1, 'vs' if z1 != '' and z2 != '' else '', z2, )

        embed.add_field(name=f'`{msg}`', value=f"\u200B", inline=False)
    embed.add_field(name=f"\u200B", value=f'You can click the respective button to view match details', inline=False)

    await interaction.send(embed=embed, ephemeral=True, view=view)


# RANKED COMMANDS

# ZRP COMMANDS

@client.slash_command(name="zrp",
                      description="Shows ZRP commands",
                      )
async def zrp(interaction: nextcord.Interaction):
    pass


@zrp.subcommand(name="store", description="Show ZRP store")
async def zrp_store(interaction: nextcord.Interaction):
    execute_before_command(interaction)
    await callback.zrp_store_callback(interaction)


@zrp.subcommand(name="stats", description="Show ZRP stats")
async def zrp_stats(interaction: nextcord.Interaction):
    execute_before_command(interaction)
    await interaction.response.defer(ephemeral=True)
    embed = CustomEmbed(title='$ZRP Stats')
    stat_obj = db_query.get_zrp_stats()
    burnt = 1589000 - (await xrpl_functions.get_zrp_balance(address=config.ISSUER['ZRP'], issuer=True))
    if stat_obj is not None:
        embed.add_field(name='$ZRP Burnt ❤️‍🔥', value=f'{burnt:.2f}', inline=False)
        embed.add_field(name='$ZRP Distributed 💰', value=f'{stat_obj["distributed"]:.2f}', inline=False)
        embed.add_field(name='$ZRP left in current Block 🏦', value=f'{stat_obj["left_amount"]:.2f}', inline=False)
        embed.add_field(name='$ZRP won in Jackpot 💸', value=f'{stat_obj["jackpot_amount"]:.2f}', inline=False)
    await interaction.edit_original_message(embed=embed)


@zrp.subcommand(name="tip", description="Send ZRP tip to someone")
async def zrp_stats(interaction: nextcord.Interaction, amount: int,
                    send_to: Optional[nextcord.Member] = SlashOption(required=True), ):
    execute_before_command(interaction)
    if amount <= 0:
        await interaction.send("Please provide a positive amount for the tip.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    user_id = interaction.user.id
    user_owned_nfts = db_query.get_owned(user_id)
    send_to_nfts = db_query.get_owned(send_to.id)

    # Sanity checks

    if user_owned_nfts is None:
        await interaction.edit_original_message(
            content="Sorry you can't use this feature, as you haven't verified your wallet",
            embeds=[], view=View())
        return
    if send_to_nfts is None:
        await interaction.edit_original_message(content=f"Sorry {send_to.mention} haven't verified their wallet yet",
                                                embeds=[], view=View())

        return
    await interaction.edit_original_message(content="Generating transaction QR code...", embeds=[], view=View())
    user_address = user_owned_nfts['address']
    uuid, url, href = await xumm_functions.gen_zrp_txn_url(send_to_nfts['address'],
                                                           user_address, amount)
    embed = CustomEmbed(color=0x01f39d, title=f"Please sign the transaction using this QR code or click here.",
                        url=href)

    embed.set_image(url=url)
    await interaction.edit_original_message(embed=embed, view=View())
    config.track_zrp_txn[user_address] = {'to': send_to_nfts['address'], 'amount': 0}
    for i in range(18):
        if config.track_zrp_txn[user_address]['amount'] == amount:
            try:
                del config.track_zrp_txn[user_address]
                await interaction.send(content='', embed=CustomEmbed(title="**Success**",
                                                                     description=f"{interaction.user.mention} tipped {send_to.mention} `{amount} ZRP`!"
                                                                     ))
                return True
            except Exception as e:
                print(traceback.format_exc())
        await asyncio.sleep(10)
    return False


# ZRP COMMANDS

# GYM COMMANDS

@client.slash_command(name="gym",
                      description="Shows Gym commands",
                      )
async def gym(interaction: nextcord.Interaction):
    pass


@gym.subcommand(name="battle", description="Start Battle against a selected Gym Leader (PvE)")
async def gym_battle(interaction: nextcord.Interaction,
                     gym_leader: str = SlashOption(name="gym_leader", description="Gym Leader Type"), ):
    execute_before_command(interaction)
    user = interaction.user

    proceed = await checks.check_gym_battle(user.id, interaction, gym_leader)
    if not proceed:
        return

    await callback.gym_callback(user.id, interaction, gym_leader)


# GYM COMMANDS

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
                                                             battle_instance['battle_type'],
                                                             battle_name='Friendly Battle')
                    else:
                        await reaction.message.edit(content="Ranked Battle **beginning**")
                        winner = await battle_function.proceed_battle(reaction.message, battle_instance,
                                                                      battle_instance['battle_type'],
                                                                      battle_name='Ranked Battle')
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
                            name=f"{t1['tier'] if winner == 2 else t2['tier']} {('🤡 Rank Down `⬇` 🤡' if loser_p > 0 else '⭐ Rank Up `⬆` ⭐') if (new_rank1 if winner == 2 else new_rank2) is not None else ''}",
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
    elif reaction.emoji == "✅":
        if config.battle_royale_started and reaction.message.id == config.battle_royale_msg:
            user_data = db_query.get_owned(user.id)

            if user_data is None:
                return
            else:
                u_flair = f' | {user_data.get("flair", [])[0]}' if len(
                    user_data.get("flair", [])) > 0 else ''
                user_mention = user.mention + u_flair
                if user_data is None or (len(user_data['zerpmons']) == 0 or len(
                        user_data['trainer_cards']) == 0 or user.id in config.ongoing_battles):
                    return
                else:
                    if user.id not in [i['id'] for i in config.battle_royale_participants]:
                        config.battle_royale_participants.append(
                            {'id': user.id, 'username': user_mention, 'address': user_data['address']})
        elif reaction.message.id in config.free_battle_royale_p:
            user_data = db_query.get_owned(user.id)
            if user_data is None:
                return
            else:
                u_flair = f' | {user_data.get("flair", [])[0]}' if len(
                    user_data.get("flair", [])) > 0 else ''
                user_mention = user.mention + u_flair
                if user_data is None or user.id in config.ongoing_battles:
                    return
                else:
                    all_p = []
                    [all_p.extend(i) for k, i in config.free_battle_royale_p.items()]
                    print(all_p, config.free_battle_royale_p)
                    if user.id not in [i['id'] for i in all_p]:
                        config.free_battle_royale_p[reaction.message.id].append(
                            {'id': user.id, 'username': user_mention, 'address': user_data['address']})
        for _id, potion_trade in config.potion_trades.copy().items():
            if user.id == potion_trade["challenged"] and _id == reaction.message.id:
                oppo = db_query.get_owned(user.id)
                config.potion_trades[_id]['active'] = True
                await reaction.message.edit(embeds=[CustomEmbed(title="**Trade Successful**!")])
                if potion_trade['trade_type'] == 1:
                    if oppo['revive_potion'] < potion_trade['amount']:
                        del config.potion_trades[_id]
                        db_query.add_mission_potion(potion_trade['address1'], potion_trade['amount'])
                        return
                    db_query.add_revive_potion(potion_trade['address2'], -potion_trade['amount'])
                    db_query.add_mission_potion(potion_trade['address2'], potion_trade['amount'])
                    db_query.add_revive_potion(potion_trade['address1'], potion_trade['amount'])
                elif potion_trade['trade_type'] == 2:
                    if oppo['mission_potion'] < potion_trade['amount']:
                        del config.potion_trades[_id]
                        db_query.add_revive_potion(potion_trade['address1'], potion_trade['amount'])
                        return
                    db_query.add_mission_potion(potion_trade['address2'], -potion_trade['amount'])
                    db_query.add_revive_potion(potion_trade['address2'], potion_trade['amount'])
                    db_query.add_mission_potion(potion_trade['address1'], potion_trade['amount'])


# Reaction Tracker


# Autocomplete functions

@set_battle_zone.on_autocomplete("zone")
async def battle_zone_autocomplete(interaction: nextcord.Interaction, item: str):
    # Determine the choices for the trainer_name option based on a condition
    user_owned = db_query.get_owned(interaction.user.id)
    if user_owned is not None and 'bg' in user_owned:
        vals = [i.replace('./static/gym/', '').replace('.png', '') for i in user_owned['bg'] if item in i]
        choices = {i: i for i in vals}
    else:
        choices = {}
    choices = dict(sorted(choices.items()))
    await interaction.response.send_autocomplete(choices)


@set_flair.on_autocomplete("flair")
async def battle_zone_autocomplete(interaction: nextcord.Interaction, item: str):
    # Determine the choices for the trainer_name option based on a condition
    user_owned = db_query.get_owned(interaction.user.id)
    if user_owned is not None and 'flair' in user_owned:
        vals = [i for i in user_owned['flair'] if item in i]
        choices = {i: i for i in vals}
    else:
        choices = {}
    choices = dict(sorted(choices.items()))
    await interaction.response.send_autocomplete(choices)


@gym_battle.on_autocomplete("gym_leader")
async def gym_autocomplete(interaction: nextcord.Interaction, item: str):
    # Determine the choices for the trainer_name option based on a condition
    user_owned = db_query.get_owned(interaction.user.id)
    if 'gym' in user_owned:
        exclude = [i for i in user_owned['gym']['won'] if user_owned['gym']['won'][i]['next_battle_t'] > time.time()]
        leaders = [leader for leader in config.GYMS if (leader not in exclude) and (item.lower() in leader.lower())]
        choices = {i: i for i in leaders}
    else:
        choices = {leader: leader for leader in config.GYMS}
    choices = dict(sorted(choices.items()))
    await interaction.response.send_autocomplete(choices)


@battle_deck.on_autocomplete("trainer_name")
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


@bid.on_autocomplete("name")
@highestbid.on_autocomplete("name")
@forceend.on_autocomplete("name")
async def autocomplete_month(interaction: nextcord.Interaction, name: str):
    names = auction_functions.get_auctions_names()
    await interaction.response.send_autocomplete(choices=names)


@claim.on_autocomplete("name")
async def autocomplete_month(interaction: nextcord.Interaction, name: str):
    claimable = auction_functions.get_to_be_claimed()
    names = []
    for claim in claimable:
        if claim["userid"] == interaction.user.id:
            names.append(claim["name"])
    await interaction.response.send_autocomplete(choices=names)


# Autocomplete functions

client.run(config.BOT_TOKEN)
