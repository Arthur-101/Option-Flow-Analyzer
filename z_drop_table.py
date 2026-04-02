import sqlite3
conn = sqlite3.connect('options_flow.db')
conn.execute('DROP TABLE IF EXISTS signals')
conn.commit()
conn.close()
print('signals table dropped')