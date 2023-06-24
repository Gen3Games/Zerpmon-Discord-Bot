import db_query
import pandas as pd

data = []
df = pd.DataFrame(columns=['Zerpmon', 'Total Matches', 'Winrate'])
for document in db_query.get_all_z():
    if 'total' in document:
        data.append({'Zerpmon': document['name'], 'Total Matches': document['total'], 'Winrate': round(document['winrate'], 2)})
    else:
        data.append({'Zerpmon': document['name'], 'Total Matches': 0, 'Winrate': 0})

df = pd.concat([df, pd.DataFrame(data)], ignore_index=True)

print(df)
df.to_excel("winrates.xlsx", index=False, header=True)