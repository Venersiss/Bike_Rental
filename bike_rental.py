import time
import pymysql
from datetime import datetime, timedelta
import pytz
from smartcard.System import readers

# Database configuration
DB_CONFIG = {
    'host': 'localhost',
    'port': 3306,
    'user': 'root',
    'password': 'root',
    'database': 'bike_rental',
    'charset': 'utf8mb4',
    'cursorclass': pymysql.cursors.DictCursor
}

RENTAL_RATE = 10  # 10 credits for 8 hours
RENTAL_DURATION = 8 * 60 * 60  # 8 hours in seconds
PH_TZ = pytz.timezone('Asia/Manila')

def get_ph_time():
    return datetime.now(PH_TZ)

def connect_to_database():
    try:
        return pymysql.connect(**DB_CONFIG)
    except pymysql.MySQLError as e:
        print(f"Database connection failed: {e}")
        return None

def read_card():
    try:
        reader = readers()[0]
        connection = reader.createConnection()
        connection.connect()
        data, sw1, sw2 = connection.transmit([0xFF, 0xCA, 0x00, 0x00, 0x00])
        if sw1 == 0x90 and sw2 == 0x00:
            return ''.join(format(x, '02X') for x in data)
    except Exception as e:
        print(f"Card read error: {e}")
    return None

def get_user_balance(connection, card_no):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT iduser FROM user WHERE CardNo = %s", (card_no,))
            user = cursor.fetchone()
            if not user:
                print("User not registered")
                print("BUZZER: ON")
                return None
            
            user_id = user['iduser']
            
            cursor.execute("""
                SELECT 
                    SUM(CASE WHEN mode = 'Top Up' THEN Credits ELSE 0 END) as topups,
                    SUM(CASE WHEN mode = 'Deduction' THEN Credits ELSE 0 END) as deductions
                FROM Credits 
                WHERE user_iduser = %s
            """, (user_id,))
            
            balance = cursor.fetchone()
            total = (balance['topups'] or 0) - (balance['deductions'] or 0)
            
            return {'user_id': user_id, 'balance': total}
    except pymysql.MySQLError as e:
        print(f"Database error: {e}")
        return None

def get_available_bikes(connection):
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT b.idBike, b.Name 
                FROM Bike b
                LEFT JOIN (
                    SELECT Bike_idBike, MAX(end_time) as last_end_time
                    FROM transactions
                    GROUP BY Bike_idBike
                ) t ON b.idBike = t.Bike_idBike
                WHERE t.last_end_time IS NOT NULL OR NOT EXISTS (
                    SELECT 1 FROM transactions WHERE Bike_idBike = b.idBike
                )
            """)
            return cursor.fetchall()
    except pymysql.MySQLError as e:
        print(f"Database error: {e}")
        return []

def process_rental(connection, user_id, card_no):
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT idtransactions, start_time 
                FROM transactions 
                WHERE user_iduser = %s AND end_time IS NULL
            """, (user_id,))
            rental = cursor.fetchone()
            
            if rental:
                duration = (get_ph_time() - rental['start_time'].replace(tzinfo=PH_TZ)).total_seconds()
                if duration > RENTAL_DURATION:
                    current_time = get_ph_time()
                    cursor.execute("""
                        INSERT INTO Credits 
                        (userId, mode, Credits, date, user_iduser)
                        VALUES (%s, 'Deduction', %s, %s, %s)
                    """, (card_no, RENTAL_RATE, current_time, user_id))
                    connection.commit()
                    print(f"Auto-deducted {RENTAL_RATE} credits for extended rental")
                else:
                    remaining = (RENTAL_DURATION - duration) / 3600
                    print(f"Bike already rented. {remaining:.1f} hours remaining")
                return
            
            available_bikes = get_available_bikes(connection)
            if not available_bikes:
                print("No bikes available")
                return
            
            print("\nAvailable Bikes:")
            for bike in available_bikes:
                print(f"{bike['idBike']}: {bike['Name']}")
            
            bike_id = int(input("Enter bike ID to rent: "))
            selected_bike = next((b for b in available_bikes if b['idBike'] == bike_id), None)
            
            if not selected_bike:
                print("Invalid bike selection")
                return
            
            current_time = get_ph_time()
            cursor.execute("""
                INSERT INTO transactions 
                (user_iduser, Bike_idBike, start_time) 
                VALUES (%s, %s, %s)
            """, (user_id, bike_id, current_time))
            
            cursor.execute("""
                INSERT INTO Credits 
                (userId, mode, Credits, date, user_iduser, Bike_idBike) 
                VALUES (%s, 'Deduction', %s, %s, %s, %s)
            """, (card_no, RENTAL_RATE, current_time, user_id, bike_id))
            
            connection.commit()
            print(f"Bike {selected_bike['Name']} rented successfully at {current_time.strftime('%Y-%m-%d %H:%M:%S')}")
            print("SOLENOID LOCK: OPENED")
            
    except (ValueError, pymysql.MySQLError) as e:
        print(f"Rental processing error: {e}")

def return_bike(connection, user_id, card_no):
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT t.idtransactions, t.Bike_idBike, t.start_time, b.Name 
                FROM transactions t
                JOIN Bike b ON t.Bike_idBike = b.idBike
                WHERE t.user_iduser = %s AND t.end_time IS NULL
            """, (user_id,))
            rental = cursor.fetchone()
            
            if not rental:
                print("No active rental found for this user")
                return False
            
            start_time = rental['start_time'].replace(tzinfo=PH_TZ)
            duration = (get_ph_time() - start_time).total_seconds()
            rental_periods = max(1, int(duration // RENTAL_DURATION) + (1 if duration % RENTAL_DURATION > 0 else 0))
            total_cost = rental_periods * RENTAL_RATE
            
            current_time = get_ph_time()
            cursor.execute("""
                UPDATE transactions 
                SET end_time = %s 
                WHERE idtransactions = %s
            """, (current_time, rental['idtransactions']))

            cursor.execute("""
                INSERT INTO Credits 
                (userId, mode, Credits, date, user_iduser, Bike_idBike)
                VALUES (%s, 'Deduction', %s, %s, %s, %s)
            """, (card_no, total_cost, current_time, user_id, rental['Bike_idBike']))
            
            connection.commit()
            print(f"Bike {rental['Name']} returned at {current_time.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"Total rental cost: {total_cost} credits")
            print("SOLENOID LOCK: CLOSED")
            return True
            
    except pymysql.MySQLError as e:
        print(f"Return processing error: {e}")
        return False

def main():
    print("=== Bike Rental RFID System ===")
    print(f"Rate: {RENTAL_RATE} credits for {RENTAL_DURATION//3600} hours")
    
    while True:
        print("\nReady to scan card...")
        card_no = read_card()
        if not card_no:
            time.sleep(1)
            continue
            
        print(f"\nCard detected: {card_no}")
        connection = connect_to_database()
        if not connection:
            time.sleep(1)
            continue
            
        try:
            user_data = get_user_balance(connection, card_no)
            if not user_data:
                time.sleep(1)
                continue
                
            print(f"Current balance: {user_data['balance']} credits")
            
            if user_data['balance'] < RENTAL_RATE:
                print(f"Insufficient balance (minimum {RENTAL_RATE} credits)")
                print("BUZZER: ON")
                time.sleep(1)
                continue
            
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT COUNT(*) as active_rentals 
                    FROM transactions 
                    WHERE user_iduser = %s AND end_time IS NULL
                """, (user_data['user_id'],))
                result = cursor.fetchone()
                has_active_rental = result['active_rentals'] > 0
            
            if has_active_rental:
                return_bike(connection, user_data['user_id'], card_no)
            else:
                process_rental(connection, user_data['user_id'], card_no)
            
        finally:
            connection.close()
            time.sleep(1)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nSystem shutdown")
