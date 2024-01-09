import time
import csv
import nextcord
import datetime
import pytz
from nextcord.ui import View
import config
import db_query
from db_query import get_owned
from utils import battle_function


class CustomEmbed(nextcord.Embed):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.set_footer(text='Zerpmon',
                        icon_url=config.ICON_URL)


def convert_timestamp_to_hours_minutes(timestamp):
    current_time = int(time.time())
    time_difference = timestamp - current_time
    if time_difference < 0:
        return None  # Timestamp is in the past
    hours = time_difference // 3600
    minutes = (time_difference % 3600) // 60
    return hours, minutes


async def get_time_left_utc(days=1):
    # Get current UTC time
    current_time = datetime.datetime.utcnow()

    # Calculate the time difference until the next UTC 00:00
    next_day = current_time + datetime.timedelta(days=days)
    target_time = next_day.replace(hour=0, minute=0, second=0, microsecond=0)
    time_difference = target_time - current_time

    # Extract the hours and minutes from the time difference
    hours_left = time_difference.total_seconds() // 3600
    minutes_left = (time_difference.total_seconds() % 3600) // 60
    seconds_left = (time_difference.total_seconds() % 60)
    return int(hours_left), int(minutes_left), int(seconds_left)


def get_next_ts():
    current_time = datetime.datetime.now(pytz.utc)
    next_day = current_time + datetime.timedelta(days=1)
    target_time = next_day.replace(hour=0, minute=0, second=0, microsecond=0)
    return target_time.timestamp()


def get_days_left(ts):
    current_time = int(time.time())
    time_difference = ts - current_time
    if time_difference < 0:
        return None  # Timestamp is in the past
    days = time_difference // 86400
    return days


def get_type_emoji(attrs, emoji=True):
    emj_list = [(config.TYPE_MAPPING[i['value']] if emoji else i['value']) for i in attrs if
                i['trait_type'] == 'Affinity' or i['trait_type'] == 'Type']
    return ', '.join(emj_list)


def convert_timestamp_to_datetime(timestamp):
    return datetime.datetime.utcfromtimestamp(timestamp)


def save_csv(data, name):
    fields = data[0].keys()
    # Writing to CSV file
    with open(name, mode="w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        for entry in data:
            entry["time"] = convert_timestamp_to_datetime(entry["time"])
            writer.writerow(entry)


def show_headers(headers):
    x_rate_limit_limit = headers.get('X-RateLimit-Limit')
    x_rate_limit_remaining = headers.get('X-RateLimit-Remaining')
    x_rate_limit_reset = headers.get('X-RateLimit-Reset')

    # Print rate limit information
    print('Rate Limit Headers:')
    print('-------------------')
    print('X-RateLimit-Limit:', x_rate_limit_limit)
    print('X-RateLimit-Remaining:', x_rate_limit_remaining)
    print('X-RateLimit-Reset:', x_rate_limit_reset)


async def check_wager_entry(interaction: nextcord.Interaction, users):
    for owned_nfts in users:
        if owned_nfts['data'] is None:
            await interaction.edit_original_message(
                content="Sorry no NFTs found for **{owned_nfts['user']}** or haven't yet verified your wallet",
                view=View())
            return False

        if len(owned_nfts['data']['zerpmons']) == 0:
            await interaction.edit_original_message(
                content=f"Sorry **0** Zerpmon found for **{owned_nfts['user']}**, need **1** to start doing wager battles",
                view=View())
            return False

        if len(owned_nfts['data']['trainer_cards']) == 0:
            await interaction.edit_original_message(
                content=f"Sorry **0** Trainer cards found for **{owned_nfts['user']}**, need **1** to start doing wager battles",
                view=View())
            return False
    return True


def get_deck_embed(deck_type, owned_nfts):
    embed2 = CustomEmbed(title=f"**{deck_type.upper()}** Decks",
                         color=0xff5252,
                         )
    embed2.add_field(name='\u200b', value='\u200B', inline=False)
    eqs = owned_nfts['equipment_decks'][f'{deck_type}_deck']
    for k, v in owned_nfts[f'{deck_type}_deck'].items():
        print(v)
        found = True
        nfts = {}
        embed2.add_field(name=f"__{deck_type.title()} Deck #{int(k) + 1 if int(k) != 0 else 'Default'}__:\n",
                         value='\u200B',
                         inline=False)
        # embed2.add_field(name='\u200b', value='\u200B', inline=False)
        new_v = v
        if 'trainer' in v and v['trainer'] != "" and v['trainer']:
            nfts['trainer'] = owned_nfts['trainer_cards'][v['trainer']]
            del new_v['trainer']
        for pos, sr in new_v.items():
            if sr:
                nfts[str(pos)] = owned_nfts['zerpmons'][sr]

        if len(nfts) == 0:
            embed2.add_field(
                name=f"Sorry looks like you haven't selected any Zerpmon for {deck_type.title()} deck #{int(k) + 1}",
                value='\u200B',
                inline=False)

        else:
            msg_str = '> __**Battle Zerpmon**__:\n' \
                      f'> \n'
            sorted_keys = sorted(nfts.keys(),
                                 key=lambda _k: (_k != "trainer", int(_k) if _k.isdigit() else float('inf')))
            print(sorted_keys)
            sorted_data = {_k: nfts[_k] for _k in sorted_keys}
            print(sorted_data)
            for serial, nft in sorted_data.items():
                print(serial)
                if serial == 'trainer':
                    trainer = nft
                    my_button = f"https://xrp.cafe/nft/{trainer['token_id']}"
                    emj = '🧙'
                    for attr in trainer['attributes']:
                        if 'Trainer Number' in attr['trait_type']:
                            emj = '⭐'
                            break
                        if attr['value'] == 'Legendary':
                            emj = '🌟'
                            break
                    msg_str = f"> **Main Trainer**:\n" \
                              f"> {emj}**{trainer['name']}**{emj}\t[view]({my_button})\n" \
                              f"> \n" + msg_str
                else:
                    eq_name = owned_nfts['equipments'][eqs[k][serial]]['name'] if eqs[k][serial] in owned_nfts[
                        'equipments'] else None
                    msg_str += f'> #{int(serial) + 1} ⭐ {nft["name"]} ⭐ {" - " + eq_name if eq_name is not None else ""}\n'
            embed2.add_field(name='\u200B', value=msg_str, inline=False)
            embed2.add_field(name='\u200b', value='\u200B', inline=False)
    print(embed2.fields)
    return embed2


async def check_trainer_cards(interaction, user, trainer_name):
    user_owned_nfts = {'data': get_owned(user.id), 'user': user.name}

    # Sanity checks

    for owned_nfts in [user_owned_nfts]:
        if owned_nfts['data'] is None:
            await interaction.send(
                f"Sorry no NFTs found for **{owned_nfts['user']}** or haven't yet verified your wallet", ephemeral=True)
            return False

        if len(owned_nfts['data']['trainer_cards']) == 0:
            await interaction.send(
                f"Sorry **0** Trainer cards found for **{owned_nfts['user']}**, need **1** to set=",
                ephemeral=True)
            return False

        if trainer_name not in [i for i in
                                list(owned_nfts['data']['trainer_cards'].keys())]:
            await interaction.send(
                f"**Failed**, please recheck the ID/Name or make sure you hold this Trainer Card",
                ephemeral=True)
            return False

    return True


async def check_battle(user_id, opponent, user_owned_nfts, opponent_owned_nfts, interaction, battle_nickname,
                       battle_type=3):
    if user_id in config.ongoing_battles or opponent.id in config.ongoing_battles:
        await interaction.send(f"Please wait, one battle is already taking place for either you or your Opponent.",
                               ephemeral=True)
        return False
    channel_clean = battle_function.check_battle_happening(interaction.channel_id)
    if not channel_clean:
        await interaction.send(f"Please wait, one battle is already taking place in this channel.",
                               ephemeral=True)
        return False

    print(opponent)
    # print([(k, v) for k, v in owned_nfts['zerpmons'].items()])

    # Sanity checks

    if user_id == opponent.id:
        await interaction.send(f"You want to battle yourself 🥲, sorry that's not allowed.")
        return False

    for owned_nfts in [user_owned_nfts, opponent_owned_nfts]:
        user_d = owned_nfts['data']
        if user_d is None:
            await interaction.send(
                f"Sorry no NFTs found for **{owned_nfts['user']}** or haven't yet verified your wallet")
            return False

        if len(user_d['zerpmons']) == 0:
            await interaction.send(
                f"Sorry **0** Zerpmon found for **{owned_nfts['user']}**, need **1** to start doing {battle_nickname} battles")
            return False

        if len(user_d['trainer_cards']) == 0:
            await interaction.send(
                f"Sorry **0** Trainer cards found for **{owned_nfts['user']}**, need **1** to start doing {battle_nickname} battles")
            return False
        def_deck = user_d.get('battle_deck', {}).get('0', {})
        entries = [i for i, j in def_deck.items() if j]
        if (battle_nickname == 'Ranked' or user_d['discord_id'] == str(user_id)) and len(entries) < battle_type + 1:
            if not def_deck.get('trainer', None):
                await interaction.send(
                    f"**{owned_nfts['user']}** you haven't set your Trainer in default deck, "
                    f"please set it and try again")
                return False
            else:
                await interaction.send(
                    f"**{owned_nfts['user']}** your default deck contains {len(entries) - 1} Zerpmon, "
                    f"need {battle_type} to do {battle_nickname} battles.")
                return False
        elif battle_nickname == 'Instant Ranked' and user_d['discord_id'] != str(user_id):
            def_deck = user_d.get('recent_deck' + (f'{battle_type}' if battle_type != 3 else ''),
                                  user_d['battle_deck'].get('0', {}))
            if len(def_deck) < battle_type + 1:
                if not def_deck.get('trainer', None):
                    await interaction.send(
                        f"**{owned_nfts['user']}** haven't set their Trainer in default deck.")
                    return False
                else:
                    await interaction.send(
                        f"**{owned_nfts['user']}**'s default deck contains {len(def_deck) - 1} Zerpmon, "
                        f"need {battle_type} to do {battle_nickname} battles.")
                    return False

    if 'Ranked' in battle_nickname:
        r_key = 'rank' + ('' if battle_type == 3 else ('5' if battle_type == 5 else '1'))
        user_rank = user_owned_nfts['data'][r_key]['tier'] if r_key in user_owned_nfts['data'] else 'Unranked'
        user_rank_tier = config.TIERS.index(user_rank)
        opponent_rank = opponent_owned_nfts['data'][r_key]['tier'] if r_key in opponent_owned_nfts[
            'data'] else 'Unranked'
        oppo_rank_tier = config.TIERS.index(opponent_rank)
        # print(user_rank_tier, [oppo_rank_tier, oppo_rank_tier - 1, oppo_rank_tier + 1])
        if user_rank_tier not in [oppo_rank_tier, oppo_rank_tier - 1, oppo_rank_tier + 1, oppo_rank_tier - 2,
                                  oppo_rank_tier + 2]:
            await interaction.send(
                f"Sorry you can't battle **{opponent_rank}** with your current {user_rank} Rank.")
            return False
    return True


async def check_gym_battle(user_id, interaction: nextcord.Interaction, gym_type):
    owned_nfts = {'data': db_query.get_owned(user_id), 'user': interaction.user.name}

    # Sanity checks

    user_d = owned_nfts['data']
    if user_d is None:
        await interaction.send(
            f"Sorry no NFTs found for **{owned_nfts['user']}** or haven't yet verified your wallet", ephemeral=True)
        return False

    if len(user_d['zerpmons']) == 0:
        await interaction.send(
            f"Sorry **0** Zerpmon found for **{owned_nfts['user']}**, need **1** to start doing Gym battles",
            ephemeral=True)
        return False

    if len(user_d['trainer_cards']) == 0:
        await interaction.send(
            f"Sorry **0** Trainer cards found for **{owned_nfts['user']}**, need **1** to start doing Gym battles",
            ephemeral=True)
        return False
    if 'gym_deck' in user_d and len(user_d['gym_deck']) > 0:
        def_deck = user_d['gym_deck']['0']
        if not def_deck.get('trainer', None):
            await interaction.send(
                f"**{owned_nfts['user']}** you haven't set your Trainer in default gym deck, "
                f"please set it and try again", ephemeral=True)
            return False
        elif len([i for i, j in def_deck.items() if j]) == 0:
            await interaction.send(
                f"**{owned_nfts['user']}** your default gym deck contains 0 Zerpmon, "
                f"need 1 to do Gym battles.", ephemeral=True)
            return False
    if 'gym' in user_d:
        # if user_d['gym']['active_t'] > time.time():
        #     _hours, _minutes, _s = await get_time_left_utc()
        #     await interaction.send(
        #         f"Sorry please wait **{_hours}**h **{_minutes}**m for your next Gym Battle.", ephemeral=True)
        #     return False
        won_gyms = user_d['gym'].get('won', {})
        exclude = [i for i in won_gyms if
                   won_gyms[i]['next_battle_t'] > time.time()]
        type_ = gym_type.lower().title()
        print(type_)
        if type_ in exclude or type_ not in config.GYMS:
            await interaction.send(
                f"Sorry please enter a valid Gym.", ephemeral=True)
            return False
    return True


async def check_boss_battle(user_id, interaction: nextcord.Interaction):
    owned_nfts = {'data': db_query.get_owned(user_id), 'user': interaction.user.name}

    # Sanity checks

    user_d = owned_nfts['data']
    if user_d is None:
        await interaction.send(
            f"Sorry no NFTs found for **{owned_nfts['user']}** or haven't yet verified your wallet", ephemeral=True)
        return False

    if len(user_d['zerpmons']) == 0:
        await interaction.send(
            f"Sorry **0** Zerpmon found for **{owned_nfts['user']}**, need **1** to start doing Boss battles",
            ephemeral=True)
        return False

    if 'battle_deck' in user_d and len(user_d['battle_deck']) > 0 and len(user_d['battle_deck']['0']) == 0:
        await interaction.send(
            f"**{owned_nfts['user']}** your default battle deck contains 0 Zerpmon, "
            f"need 1 to do Boss battles.", ephemeral=True)
        return False
    if 'boss_battle_stats' in user_d:
        # if user_d['gym']['active_t'] > time.time():
        #     _hours, _minutes, _s = await get_time_left_utc()
        #     await interaction.send(
        #         f"Sorry please wait **{_hours}**h **{_minutes}**m for your next Gym Battle.", ephemeral=True)
        #     return False
        valid = user_d['boss_battle_stats']['next_battle_t'] < time.time()
        if not valid:
            h, m, s = await get_time_left_utc()
            await interaction.send(
                f"Sorry, you have to wait **{h}**h **{m}**m for doing Boss Battles.", ephemeral=True)
            return False
    if not config.boss_active:
        await interaction.send(
            f"Please wait until the World Boss is summoned. (<t:{config.boss_reset_t}:R>)", ephemeral=True)
        return False
    return True


def get_temp_candy(zerp_doc):
    for candY_key, emj in config.TEMP_CANDIES.items():
        if zerp_doc.get(candY_key, 0) > time.time():
            return emj
    return ''


def get_show_zerp_embed(zerpmon, interaction, omni=False):
    lvl, xp, w_candy, g_candy, l_candy = db_query.get_lvl_xp(zerpmon['name'], get_candies=True)
    temP_candy_emj = get_temp_candy(zerpmon)
    embed = CustomEmbed(
        title=f"{temP_candy_emj} **{zerpmon['name']}** {temP_candy_emj}" + (
            f' (**Ascended** ☄️)' if zerpmon.get("ascended", False) else ''),
        color=0xff5252,
    )
    my_button = f"https://xrp.cafe/nft/{zerpmon['nft_id']}"
    if omni:
        nft_type = '🌟'
    else:
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
                  (
                      f"> Type: {'🌟' if omni else config.TYPE_MAPPING[move['type'].replace(' ', '')]}\n" if 'type' in move else "") + \
                  f"> Percentage: {move['percent']}%\n",
            inline=False)
    if interaction is not None:
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
    return embed


def populate_lvl_up_embed(zerp_doc, lvl_obj, is_lvl_up, reward_list):
    embed = CustomEmbed(title=f"Level Up ⬆{lvl_obj['level']}" if is_lvl_up else f"\u200B",
                        color=0xff5252,
                        )
    my_button = f"https://xrp.cafe/nft/{zerp_doc.get('token_id', zerp_doc['nft_id'])}"
    nft_type = ', '.join([i['value'] for i in zerp_doc['attributes'] if i['trait_type'] == 'Type'])
    ascended = zerp_doc.get("ascended", False)
    embed.add_field(
        name=f"**{zerp_doc['name']}** ({nft_type})" + (f' (**Ascended** ☄️)' if ascended else ''),
        value=f"> Level: **{lvl_obj['level']}/{'30' if not ascended else '60'}**\n"
              f"> XP: **{lvl_obj['xp']}/{lvl_obj['xp_required']}**\n"
              f'> [view]({my_button})', inline=False)
    if is_lvl_up:
        embed.add_field(name="Level Up Rewards: ",
                        value=f"\u200B"
                        ,
                        inline=False)
        if 'rp' in reward_list:
            embed.add_field(name="Revive All Potions: ",
                            value=f"**{reward_list['rp']}**"
                                  + '\t🍶',
                            inline=False)
            embed.add_field(name="Mission Refill Potions: ",
                            value=f"**{reward_list['mp']}**"
                                  + '\t🍶',
                            inline=False)
        if 'cf' in reward_list:
            embed.add_field(name="Candy Fragment: ",
                            value=f"**{reward_list['cf']}**"
                                  + '\t🧩',
                            inline=False)
            embed.add_field(name="Candy Slot: ",
                            value=f"**{reward_list.get('cs', 0)}**"
                                  + '\t📥',
                            inline=False)
        if 'grp' in reward_list:
            embed.add_field(name="Gym Refill Potions: ",
                            value=f"**{reward_list['grp']}**"
                                  + '\t🍵',
                            inline=False)
            cndy = reward_list.get('extra_candy')
            if cndy:
                del reward_list['extra_candy']
                reward_list[cndy] = 1
            for i, emj in config.TEMP_CANDIES.items():
                if i in reward_list:
                    embed.add_field(name=f"{(i.replace('_', ' ').title())}: ",
                                    value=f"**{reward_list[i]}**\t{emj}",
                                    inline=False)
    embed.set_image(
        url=zerp_doc['image'] if "https:/" in zerp_doc['image'] else 'https://cloudflare-ipfs.com/ipfs/' + zerp_doc[
            'image'].replace("ipfs://", ""))
    return embed
