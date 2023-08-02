import time

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
    # Get the current time in UTC
    current_time = datetime.datetime.now(pytz.utc)

    # Calculate the time difference until the next UTC 00:00
    next_day = current_time + datetime.timedelta(days=1)
    target_time = next_day.replace(hour=0, minute=0, second=0, microsecond=0)
    return target_time.timestamp()


async def check_wager_entry(interaction: nextcord.Interaction, users):
    for owned_nfts in users:
        if owned_nfts['data'] is None:
            await interaction.edit_original_message(
                content="Sorry no NFTs found for **{owned_nfts['user']}** or haven't yet verified your wallet", view=View())
            return False

        if len(owned_nfts['data']['zerpmons']) == 0:
            await interaction.edit_original_message(
                content=f"Sorry **0** Zerpmon found for **{owned_nfts['user']}**, need **1** to start doing wager battles", view=View())
            return False

        if len(owned_nfts['data']['trainer_cards']) == 0:
            await interaction.edit_original_message(
                content=f"Sorry **0** Trainer cards found for **{owned_nfts['user']}**, need **1** to start doing wager battles", view=View())
            return False
    return True


def get_deck_embed(deck_type, owned_nfts):
    embed2 = CustomEmbed(title=f"**{deck_type.upper()}** Decks",
                         color=0xff5252,
                         )
    embed2.add_field(name='\u200b', value='\u200B', inline=False)
    for k, v in owned_nfts[f'{deck_type}_deck'].items():
        print(v)
        found = True
        nfts = {}
        embed2.add_field(name=f"{deck_type.title()} Deck #{int(k) + 1 if int(k) != 0 else 'Default'}:\n", value='\u200B',
                         inline=False)
        embed2.add_field(name='\u200b', value='\u200B', inline=False)
        new_v = v
        if 'trainer' in v and v['trainer'] != "":
            nfts['trainer'] = owned_nfts['trainer_cards'][v['trainer']]
            del new_v['trainer']
        for pos, sr in new_v.items():
            nfts[str(pos)] = owned_nfts['zerpmons'][sr]

        if len(nfts) == 0:
            embed2.add_field(name=f"Sorry looks like you haven't selected any Zerpmon for {deck_type.title()} deck #{int(k) + 1}",
                             value='\u200B',
                             inline=False)

        else:
            msg_str = '> Battle Zerpmons:\n' \
                      f'> \n'
            sorted_keys = sorted(nfts.keys(), key=lambda _k: (_k != "trainer", int(_k) if _k.isdigit() else float('inf')))
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
                    msg_str = f"> Main Trainer:\n" \
                              f"> {emj}**{trainer['name']}**{emj}\t[view]({my_button})\n" \
                              f"> \n" + msg_str
                else:
                    msg_str += f'> #{int(serial) + 1} ⭐ {nft["name"]} ⭐\n'
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


async def check_battle(user_id, opponent, user_owned_nfts, opponent_owned_nfts, interaction, battle_nickname):
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
        if battle_nickname == 'Ranked' and 'battle_deck' in user_d and len(user_d['battle_deck']) > 0 and len(user_d['battle_deck']['0']) < 4:
            def_deck = user_d['battle_deck']['0']
            if 'trainer' not in def_deck:
                await interaction.send(
                    f"**{owned_nfts['user']}** you haven't set your Trainer in default deck, "
                    f"please set it and try again")
                return False
            else:
                await interaction.send(
                    f"**{owned_nfts['user']}** your default deck contains {len(def_deck) - 1} Zerpmon, "
                    f"need 3 to do {battle_nickname} battles.")
                return False

    if battle_nickname == 'Ranked':
        user_rank = user_owned_nfts['data']['rank']['tier'] if 'rank' in user_owned_nfts['data'] else 'Unranked'
        user_rank_tier = config.TIERS.index(user_rank)
        opponent_rank = opponent_owned_nfts['data']['rank']['tier'] if 'rank' in opponent_owned_nfts['data'] else 'Unranked'
        oppo_rank_tier = config.TIERS.index(opponent_rank)
        # print(user_rank_tier, [oppo_rank_tier, oppo_rank_tier - 1, oppo_rank_tier + 1])
        if user_rank_tier not in [oppo_rank_tier, oppo_rank_tier - 1, oppo_rank_tier + 1, oppo_rank_tier - 2, oppo_rank_tier + 2]:
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
            f"Sorry **0** Zerpmon found for **{owned_nfts['user']}**, need **1** to start doing Gym battles", ephemeral=True)
        return False

    if len(user_d['trainer_cards']) == 0:
        await interaction.send(
            f"Sorry **0** Trainer cards found for **{owned_nfts['user']}**, need **1** to start doing Gym battles", ephemeral=True)
        return False
    if 'gym_deck' in user_d and len(user_d['gym_deck']) > 0 and len(user_d['gym_deck']['0']) < 2:
        def_deck = user_d['gym_deck']['0']
        if 'trainer' not in def_deck:
            await interaction.send(
                f"**{owned_nfts['user']}** you haven't set your Trainer in default gym deck, "
                f"please set it and try again", ephemeral=True)
            return False
        else:
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
        exclude = [i for i in user_d['gym']['won'] if
                       user_d['gym']['won'][i]['next_battle_t'] > time.time()]
        type_ = gym_type.lower().title()
        print(type_)
        if type_ in exclude or type_ not in config.GYMS:
            await interaction.send(
                f"Sorry please enter a valid Gym.", ephemeral=True)
            return False
    return True
