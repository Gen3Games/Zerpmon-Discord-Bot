# ![Logo](https://cdn.discordapp.com/avatars/1093248198480498800/14e4b1c2afb3f1af0b1992a48a536545.webp?size=100)

# [ZERPMON DISCORD BOT](https://www.zerpmon.world/)
[![Discord Online](https://img.shields.io/discord/1057099363421274123?label=Chat&style=flat-square&logo=discord&colorB=7289DA)](https://discord.gg/bzemAd3D)

[![Twitter](https://img.shields.io/twitter/follow/zerpmonxrp?style=social)](https://twitter.com/zerpmonxrp)


[//]: # ()
[//]: # (> ❗ Note: Zerpmon Bot will move over to COGS in the future as it expands.)

---

## Commands<a name="commands"></a>

- `/ping`: *Check if the bot is online.*
- [`/wallet`](#wallet): *Verify your XRPL wallet.*
- [`/show`](#show): *Show owned Zerpmon or Trainer cards.*
- [`/battle`](#battle): *Engage in a friendly battle with other Trainers.*
- [`/mission`](#mission): *Participate in PvE/Solo Combat missions with your Zerpmon.*
- [`/battle_royale`](#battle_royale): *Join a Battle Royale, where multiple players compete.*
- [`/trade_nft`](#trade_nft): *Trade NFTs with other users.*
- [`/show_deck`](#show_deck): *Display selected Zerpmon for Mission and Battle Decks.*
- [`/store`](#store): *Browse available items in the Zerpmon store.*
- [`/show_zerpmon`](#show_zerpmon): *View detailed statistics of a Zerpmon.*

---

- `/add`: *Set Zerpmon (for missions or battles).*
    - `/add trainer_deck`: *Set Trainer for specific Battle Decks.*
    - `/add battle_deck`: *Add Zerpmon to a specific Battle Deck (up to 5 Zerpmons).*
    - `/add default_deck`: *Set Default Battle Deck.*
    - `/add mission_deck`: *Set Zerpmon for Solo Missions.*

- `/buy`: *Purchase Revive or Mission Refill potions using XRP.*
    - `/buy revive_potion`: *Buy Revive All Potion using XRP (1 use).*
    - `/buy mission_refill`: *Buy Mission Refill Potion using XRP (10 Missions).*

- `/use`: *Use Revive or Mission Refill potions.*
    - `/use revive_potion`: *Use Revive All Potion to revive all Zerpmon for Solo Missions.*
    - `/use mission_refill`: *Use Mission Refill Potion to reset 10 missions for the day.*

- `/gift`: *Gift Potions (only server admins can use this).*
    - `/gift revive_potion`: *Gift Revive All Potion (only server admins can use this).*
    - `/gift mission_refill`: *Gift Mission Refill Potion (only server admins can use this).*

- `/wager_battle`: *Engage in a wagered battle between Trainers (XRP or NFTs).*
    - `/wager_battle xrp`: *Battle by wagering equal amounts of XRP (Winner takes all).*
    - `/wager_battle nft`: *Battle by wagering 1-1 NFT (Winner takes both).*
    - `/wager_battle battle_royale`: *Battle Royale by wagering equal amounts of XRP (Winner takes all).*

- `/show_leaderboard`: *Display the Leaderboard.*
    - `/show_leaderboard pve`: *Show PvE Leaderboard.*
    - `/show_leaderboard pvp`: *Show PvP Leaderboard.*

---

### /wallet<a name="wallet"></a>

Requires the "**Zerpmon Holder**" and "**Trainer**" roles to be added beforehand in a server.

```python
roles = interaction.guild.roles
z_role = nextcord.utils.get(roles, name="Zerpmon Holder")
t_role = nextcord.utils.get(roles, name="Trainer")
if z_role in interaction.user.roles or t_role in interaction.user.roles:
    await interaction.send(f"You are already verified!")
    return
```

When a new user uses this command Bot generates a new QR code/ Http URL using Xumm API.<br>
User can then sign up using it, Bot will start gathering all their owned NFTs using XRPL client

```python
client = AsyncJsonRpcClient("https://...")
all_nfts = []

acct_info = AccountNFTs(
    account=address,
    limit=400,
)
response = await client.request(acct_info)
result = response.result
```

Once done Bot will give User **Zerpmon Holder**/**Trainer** roles based on their NFT holding

```python
if len(user_obj['zerpmons']) > 0:
    await interaction.user.add_roles(z_role)
if len(user_obj['trainer_cards']) > 0:
    await interaction.user.add_roles(t_role)
# Save the address to stop dual accounts
user_obj['address'] = address
db_query.save_user(user_obj)
```

---

### /show<a name="show"></a>

Once the wallet is signed in through Xumm, users can view their Zerpmon and Zerpmon Trainer
NFT holdings.
> Note: It might take a minute if there are multiple users signing up simultaneously

---

### /battle<a name="battle"></a>

- PARAMS
    - opponent : *User you wanna battle against*
    - type : *Battle Type (1v1, 2v2, 3v3 ...)*

```python
async def battle(interaction: nextcord.Interaction, opponent: Optional[nextcord.Member] = SlashOption(required=True),
                 type: int = SlashOption(
                     name="picker",
                     choices={"1v1": 1, "2v2": 2, "3v3": 3, "4v4": 4, "5v5": 5},
                 ),
                 ):
```

> Users can battle each other if they hold at least 1 Zerpmon and Trainer NFT

```python
msg = await interaction.channel.send(
    f"**{type}v{type}** Friendly **battle** challenge to {opponent.mention} by {interaction.user.mention}. Click the **swords** to accept!")
await msg.add_reaction("⚔")
config.battle_dict[msg.id] = {
    "type": 'friendly',
    "challenger": user_id,
    ...
}
```

Once the User reacts to the message Battle starts until all Zerpmons of one user are KO'd

```python
try:
    config.battle_dict[_id]['active'] = True
    await reaction.message.edit(content="Battle **beginning**")
    # proceed_battle function from ./utils/battle_function
    await battle_function.proceed_battle(reaction.message, battle_instance,
                                         battle_instance['battle_type'])
except Exception as e:
    logging.error(f"ERROR during friendly battle: {e}\n{traceback.format_exc()}")
finally:
    del config.battle_dict[_id]
```

---

### /mission<a name="mission"></a>

> Users can do missions with their Zerpmon if they hold at least 1 Zerpmon NFT

```python
    try:
    # proceed_mission function from ./utils/battle_function
    loser = await battle_function.proceed_mission(interaction, user_id, _battle_z[0], _b_num)
    if loser == 1:
        mission_zerpmon_used = True
except Exception as e:
    logging.error(f"ERROR during mission: {e}\n{traceback.format_exc()}")
    return
finally:
    config.ongoing_missions.remove(user_id)
```

- A user can do max 10 in one day or they will need to use a mission refill potion
- Once the User's Zerpmon is KO'd a button to revive it or use another Zerpmon (if they own
  more than 1) is shown.

```python
r_button = Button(label="Revive Zerpmon", style=ButtonStyle.green)
r_view = View()
r_view.add_item(r_button)
r_view.timeout = 120
r_button.callback = lambda i: use_revive_potion(interaction)
```

- Zerpmon auto revive and Missions reset at UTC 00:00 every day

---

### /battle_royale<a name="battle_royale"></a>

- PARAMS
    - start_after : *How long before a Battle royale starts 1 min, 2 min, or 3 min*

```python
 async def battle_royale(interaction: nextcord.Interaction, start_after: int = SlashOption(
    name="start_after",
    choices={"1 min": 1, "2 min": 2, "3 min": 3},
), ):
```

> Users can take part in 1v1 Battle royale if they hold at least 1 Zerpmon and Trainer NFT

This shows a responsive timer which updates every 10s:

```python
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
```

Once the User reacts to the message he is entered in an array of participants if he/she holds Both NFTs

```python
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
```

At each round two random participants are selected from that array,
they battle each other, the winner is retained inside the array.<br>
This process repeats until only the winner is left.

```python
random_ids = random.sample(config.battle_royale_participants, 2)
# Remove the selected players from the array
config.battle_royale_participants = [id_ for id_ in config.battle_royale_participants if id_ not in random_ids]

battle_instance = {
    "type": 'friendly',
    "challenger": random_ids[0]['id'],
    ...
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
    del config.battle_dict[msg.id]

```

---

### /trade_nft<a name="trade_nft"></a>

- PARAMS
    - your_nft_id : *The NFTokenID of the NFT you wanna Trade*
    - opponent : *The other user with whom you wanna trade the NFT*
    - opponent_nft_id : *The NFTokenID of the NFT the other user wanna Trade*

```python
async def trade_nft(interaction: nextcord.Interaction, your_nft_id: str, opponent_nft_id: str,
                    opponent: Optional[nextcord.Member] = SlashOption(required=True),
                    ):
```

If the parameters are valid, the bot will send a message to both users, providing the details of the NFTs involved in
the trade. The message will also include instructions for both users to send their respective NFTs to the bot's wallet
with an easy to use Button "SEND NFT".
The callback of this Button looks like this:

```python
await _i.send(content="Generating transaction QR code...", ephemeral=True)
if _i.user.id == user_id:
    nft_id = your_nft_id
else:
    nft_id = opponent_nft_id
    user_address = db_query.get_owned(_i.user.id)['address']
    uuid, url, href = await xumm_functions.gen_nft_txn_url(user_address, nft_id)
    embed = nextcord.Embed(color=0x01f39d,
                           title=f"Please sign the transaction using this QR code or click here.",
                           url=href)

    embed.set_image(url=url)

    await _i.send(embed=embed, ephemeral=True, )
```

- Once the user signs this transaction (Txn), their NFT is transferred to the bot's wallet.
- After confirming that both NFTs have arrived, the bot facilitates the transfer between the users' wallets, completing
  the trade.
- If only one user sends their NFT, it will be automatically returned to them within a few minutes.

```python
await msg.reply(
    f'Sending transaction for `{your_nft_id}` to {opponent.mention} and `{opponent_nft_id}` to {interaction.user.mention}')
# send_nft_tx function from ./utils/xrpl_ws
saved1 = await xrpl_ws.send_nft_tx(user_owned_nfts['address'],
                                   [opponent_nft_id])

saved2 = await xrpl_ws.send_nft_tx(opponent_owned_nfts['address'],
                                   [your_nft_id])
if not (saved1 and saved2):
    await msg.reply(f"**Failed**, something went wrong while sending the Txn")
else:
    await msg.reply(f"**Successfully** sent `{your_nft_id}` and `{opponent_nft_id}`")

```

### /show_deck<a name="show_deck"></a>

Users can view their Zerpmon Battle decks using this command.<br>
It retrieves their Zerpmon Decks and shows it in an embed with added stats(lvl/xp)

```python
await msg.edit(
    content="FOUND" if found else "No deck found try to use `/add battle` or `/add mission` to create now"
    , embeds=embeds, )
```

---

### /store<a name="store"></a>

Users can open up Zerpmon Store for checking the price of Potions using this command.<br>
It also includes two attached Buttons for buying each Potion (Mission Refill or Revive )

```python
b1 = Button(label="Buy Revive All Potion", style=ButtonStyle.blurple)
b2 = Button(label="Buy Mission Refill Potion", style=ButtonStyle.blurple)
view = View()
view.add_item(b1)
view.add_item(b2)
view.timeout = 120
# Add the button callback to the button
b1.callback = lambda i: purchase_callback(i, config.POTION[0])
b2.callback = lambda i: purchase_callback(i, config.MISSION_REFILL[0])
```

---

### /show_zerpmon<a name="show_zerpmon"></a>

- Params
    - zerpmon_name_or_nft_id : *The name or NfTokenId of the Zerpmon NFT you wanna check*<br>

Users can view a specific Zerpmon with it's complete stats, moves, lvl, etc.

```python
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
    value=f"> **{move['name']}** \n" +
          (f"> Status Affect: `{notes}`\n" if notes != '' else "") +
          (f"> DMG: {move['dmg']}\n" if 'dmg' in move else "") +
          (f"> Stars: {len(move['stars']) * '★'}\n" if 'stars' in move else "") +
          (f"> Type: {config.TYPE_MAPPING[move['type'].replace(' ', '')]}\n" if 'type' in move else "") +
          f"> Percentage: {move['percent']}%\n",
    inline=False)
```

---

## Detecting User Transactions on XRPL<a name="xrplWs"></a>
- We define a Websocket function that subscribes to XRPL (XRP Ledger) for broadcasting new 
transactions happening.
- Also it handles disconnections by checking whether the WS is open.
```python
async with AsyncWebsocketClient(URL) as client:
  # set up the `listener` function as a Task
  asyncio.create_task(listener(client, Address, config.WAGER_ADDR))

  # now, the `listener` function will run as if
  # it were "in the background", doing whatever you
  # want as soon as it has a message.

  # subscribe to txns
  subscribe_request = Subscribe(
    streams=[StreamParameter.TRANSACTIONS],
    accounts=["rX..."]
  )
  await client.send(subscribe_request)

  while True:
    if AsyncWebsocketClient.is_open(client):
      logging.error("WS running...")
      await asyncio.sleep(60)
    else:
      try:
        await client.send(subscribe_request)
      except Exception as e:
        logging.error(f'EXECPTION inner WS sending req: {e}')
        break
```

- All new transactions are passed to the `listener(...)` function, which filters
transactions with `Destination` set to Bot's wallet.

```python
async def listener(client, store_address, wager_address):
    async for msg in client:
        try:
            if 'transaction' in msg:
                message = msg['transaction']
                if 'TransactionType' in message and message['TransactionType'] == "Payment" and \
                        'Destination' in message and message['Destination'] in [store_address, wager_address]:
                    # proceed
                    ...
```
