import sqlite3

# Connect to database
conn = sqlite3.connect("options_flow.db")
cursor = conn.cursor()

# Empty the table
# cursor.execute("DELETE FROM options_chain")
# cursor.execute("UPDATE sqlite_sequence SET seq = 984 WHERE name = 'options_chain'")  # reset autoincrement

# Commit changes
conn.commit()

# Close connection
conn.close()
