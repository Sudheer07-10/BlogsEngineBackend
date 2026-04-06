import os
from supabase import create_client

def debug_supabase():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        print("Missing SUPABASE credentials")
        return

    client = create_client(url, key)
    
    print("\n--- Testing user_configs table ---")
    try:
        # Check if table is reachable
        res = client.table("user_configs").select("*").limit(1).execute()
        print("Table reachable. Data:", res.data)
        
        # Test a mock upsert
        mock_id = "test-debug"
        mock_data = {
            "id": mock_id,
            "email": "test@example.com",
            "platform": "cp",
            "config": {"test": True}
        }
        res_upsert = client.table("user_configs").upsert(mock_data).execute()
        print("Upsert result:", res_upsert.data)
        
        # Cleanup
        client.table("user_configs").delete().eq("id", mock_id).execute()
        print("Cleanup successful")
        
    except Exception as e:
        print("ERROR:", str(e))

if __name__ == "__main__":
    debug_supabase()
