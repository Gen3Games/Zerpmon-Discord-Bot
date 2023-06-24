import time

import nextcord
import datetime
import pytz

import config
import db_query
from db_query import get_owned
from utils import battle_function


async def get_time_left_utc():
    # Get current UTC time
    current_time = datetime.datetime.utcnow()

    # Calculate the time difference until the next UTC 00:00
    next_day = current_time + datetime.timedelta(days=1)
    target_time = next_day.replace(hour=0, minute=0, second=0, microsecond=0)
    time_difference = target_time - current_time

    # Extract the hours and minutes from the time difference
    hours_left = time_difference.total_seconds() // 3600
    minutes_left = (time_difference.total_seconds() % 3600) // 60
    return int(hours_left), int(minutes_left)


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
            await interaction.send(
                f"Sorry no NFTs found for **{owned_nfts['user']}** or haven't yet verified your wallet")
            return False

        if len(owned_nfts['data']['zerpmons']) == 0:
            await interaction.send(
                f"Sorry **0** Zerpmon found for **{owned_nfts['user']}**, need **1** to start doing wager battles")
            return False

        if len(owned_nfts['data']['trainer_cards']) == 0:
            await interaction.send(
                f"Sorry **0** Trainer cards found for **{owned_nfts['user']}**, need **1** to start doing wager battles")
            return False
    return True


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


async def check_battle(user_id, opponent, interaction, battle_nickname):
    if user_id in config.ongoing_battles or opponent.id in config.ongoing_battles:
        await interaction.send(f"Please wait, one battle is already taking place for either you or your Opponent.",
                               ephemeral=True)
        return False
    channel_clean = battle_function.check_battle_happening(interaction.channel_id)
    if not channel_clean:
        await interaction.send(f"Please wait, one battle is already taking place in this channel.",
                               ephemeral=True)
        return False

    user_owned_nfts = {'data': db_query.get_owned(user_id), 'user': interaction.user.name}
    opponent_owned_nfts = {'data': db_query.get_owned(opponent.id), 'user': opponent.name}

    print(opponent)
    # print([(k, v) for k, v in owned_nfts['zerpmons'].items()])

    # Sanity checks
    if battle_nickname == 'Ranked':
        user_rank = user_owned_nfts['data']['rank']['tier'] if 'rank' in user_owned_nfts['data'] else 'Unranked'
        user_rank_tier = config.TIERS.index(user_rank)
        opponent_rank = opponent_owned_nfts['data']['rank']['tier'] if 'rank' in opponent_owned_nfts['data'] else 'Unranked'
        oppo_rank_tier = config.TIERS.index(opponent_rank)
        print(user_rank_tier, [oppo_rank_tier, oppo_rank_tier - 1, oppo_rank_tier + 1])
        if user_rank_tier not in [oppo_rank_tier, oppo_rank_tier - 1, oppo_rank_tier + 1]:
            await interaction.send(
                f"Sorry you can't battle **{opponent_rank}** with your current {user_rank} Rank.")
            return False
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
    return True
