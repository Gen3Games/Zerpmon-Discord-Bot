import asyncio
import time
import nextcord
import config


class CustomEmbed(nextcord.Embed):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.set_footer(text='Zerpmon',
                        icon_url=config.ICON_URL)


async def trade_item(interaction: nextcord.Interaction, op, user_obj, op_obj, key, name, user_item, op_item, fn):
    user_qty = user_obj[key]
    user_qty = len([i for i in user_qty if user_item in i])
    if user_obj is None or user_qty < 1:
        await interaction.edit_original_message(
            content=f"Sorry you don't have **{user_item}** {name}.")
        return False
    elif op_obj is None:
        await interaction.edit_original_message(
            content=f"Sorry **{op.name}** haven't verified their wallet yet.")
        return False
    else:
        try:
            on_hold = False
            # Put potions on hold os user doesn't spam
            user_mention = user_obj['mention']
            oppo_mention = op_obj['mention']
            fn(user_obj['discord_id'], user_item, -1)
            on_hold = True
            embed = CustomEmbed(title="Trade request",
                                description=f'{oppo_mention}, {user_mention} wants to trade their {user_item} {name} for your {op_item} {name}\n',
                                color=0x01f39d)
            embed.add_field(name="React with a ✅ if you agree to this Trade", value='\u200B')
            msg = await interaction.channel.send(embed=embed)
            await msg.add_reaction("✅")
            config.trades[msg.id] = {
                "challenger": interaction.user.id,
                "username1": user_mention,
                "item1": user_item,
                "challenged": op.id,
                "username2": oppo_mention,
                "item2": op_item,
                "active": False,
                "channel_id": interaction.channel_id,
                "timeout": time.time() + 60,
                "amount": 1,
                "key": key,
                "fn": fn
            }
            await asyncio.sleep(60)
            if msg.id in config.trades and config.trades[msg.id]['active'] == False:
                del config.trades[msg.id]
                await msg.edit(embeds=[CustomEmbed(title=f"Timed out!",
                                                   description=f"<t:{int(time.time())}:R>\n**Info**: {oppo_mention}, {user_mention} wanted to trade their {user_item} {name} for your {op_item} {name}")])
                await msg.add_reaction("❌")
                if on_hold:
                    fn(user_obj['discord_id'], user_item, 1)
        except:
            if msg.id in config.trades and config.trades[msg.id]['active'] == False:
                del config.trades[msg.id]
                if on_hold:
                    fn(user_obj['discord_id'], user_item, 1)