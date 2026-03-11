## Excel Restaurant Pos

Restaurant Order and Billing Management System

#### License

MIT


# Clover : 


frappe@c3fae21d27c7:/workspace/development/pos-bench/apps/excel_restaurant_pos$ bench --site pos.localhost console

Apps in this namespace:
frappe, erpnext, excel_restaurant_pos, excel_erpnext, frappe_uberdirect, hrms

In [1]: from excel_restaurant_pos.api.clover.clover_api import clear_token_cache
   ...: 
   ...: doc = frappe.get_single("Clover Integration")
   ...: doc.merchant_id = "5Y3AY4P5DAVD1"
   ...: doc.access_token = "ee06a485-387f-3efd-d511-3dbfbbea5c20"
   ...: doc.save(ignore_permissions=True)
   ...: frappe.db.commit()
   ...: clear_token_cache()
   ...: 
   ...: # Verify
   ...: doc2 = frappe.get_single("Clover Integration")
   ...: print("merchant_id:", doc2.merchant_id)
   ...: print("has token:", bool(doc2.access_token))
   ...: 
merchant_id: 5Y3AY4P5DAVD1
has token: True

In [2]: 