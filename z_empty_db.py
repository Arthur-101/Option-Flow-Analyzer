import sqlite3

# Connect to database
conn = sqlite3.connect("options_flow.db")
cursor = conn.cursor()

# Empty the table
cursor.execute("DELETE FROM options_chain")

# Commit changes
conn.commit()

# Close connection
conn.close()
