import frappe
from frappe.model.document import Document
from excel_restaurant_pos.api.bom import run_bom_process

class TableOrder(Document):
    def before_save(self):
        # Initialize discount and calculate total amount
        discount = float(self.discount) if self.discount else 0.0
        total_amount = self.get_total_amount()
        tax_amount = self.get_tax_amount()

        # Calculate total amount after discount and include tax
        total_amount_after_discount = total_amount - discount
        self.tax = tax_amount
        self.amount = total_amount

        self.total_amount = total_amount_after_discount + tax_amount
        
        if self.status == 'Preparing':
            self.update_item_accepted(is_accepted=1)
        if self.status == 'Ready to Serve':
            self.update_item_readiness(is_ready=1)
            
            if self.is_paid:
                self.status = 'Completed'
                self.group_and_merge_items_by_parcel()
                self.docstatus = 1 
   
        if self.status == 'Completed' and self.is_paid:
            self.group_and_merge_items_by_parcel()
            self.docstatus = 1

        # Handle 'Work in progress' status
        if self.status == 'Work in progress':
            if self.is_paid and all(item.is_ready == 1 for item in self.item_list):
                self.status = 'Completed'
                self.docstatus = 1
                return
            elif all(item.is_accepted == 1 for item in self.item_list):
                self.status = 'Preparing'
        if self.status == 'Preparing':
            if all(item.is_ready == 1 for item in self.item_list):
                self.status = 'Ready to Serve'
        self.update_order_placed_time()
    def get_total_amount(self):
        # Calculate the total amount based on rate and qty
        return sum(float(item.rate) * float(item.qty) for item in self.item_list)

    def get_tax_amount(self):
        # Calculate the tax amount based on settings
        restaurant_settings = frappe.get_doc("Restaurant Settings")
        if restaurant_settings.charge_type == 'On Net Total' and restaurant_settings.tax_rate:
            tax_rate = float(restaurant_settings.tax_rate) / 100
            discount = float(self.discount) if self.discount else 0.0
            return (self.get_total_amount() - discount) * tax_rate
        return 0.0

    def update_item_readiness(self, is_ready):
        # Helper method to update item readiness
        for item in self.item_list:
            item.is_ready = is_ready
    def update_item_accepted(self, is_accepted):
        # Helper method to update item readiness
        for item in self.item_list:
            item.is_accepted = is_accepted
    def group_and_merge_items_by_parcel(self):
        # Group items by 'item_name' and 'is_parcel'
        grouped_items = {}
        for item in self.item_list:
            key = f"{item.item}_{item.is_parcel}"  # Create a unique key for grouping
            if key in grouped_items:
                # If the item already exists, sum up the quantities and amounts
                grouped_items[key]["qty"] += item.get("qty", 0)
                grouped_items[key]["amount"] += item.get("amount", 0)
            else:
                # Otherwise, initialize the grouped item
                grouped_items[key] = {
                    "item": item.get("item"),
                    "is_parcel": item.get("is_parcel"),
                    "qty": item.get("qty", 0),
                    "rate": item.get("rate", 0),
                    "amount": item.get("amount", 0),
                    "is_ready": item.get("is_ready", 0),
                    "is_accepted": item.get("is_accepted", 0),
                    "is_create_recipe": item.get("is_create_recipe", 0),
                    "order_placed_time": item.get("order_placed_time", 0),
                    "order_accepted_time": item.get("order_accepted_time", 0),
                    "order_ready_time": item.get("order_ready_time", 0),
                    "order_confirm_time": item.get("order_confirm_time", 0),
                    "custom_is_gift_card_item": item.get("custom_is_gift_card_item", 0),
                    "custom_gift_card_type": item.get("custom_gift_card_type"),
                    "custom_gift_card_code": item.get("custom_gift_card_code"),
                    "custom_gift_amount": item.get("custom_gift_amount"),
                }
        
        # Update the document's item_list with the grouped items
        self.item_list = []
        for item_data in grouped_items.values():
            self.append("item_list", item_data)


    def on_update(self):
        if self.status == 'Completed':
            return
        for item in self.item_list:
            check_recipe=frappe.get_doc("Item",item.item)
            if bool(check_recipe.custom_is_recipe) and bool(item.is_ready) and not bool(item.is_create_recipe):
                # create Console Log Doctype
                log_message=f"Creating recipe for item {item.item} in order {self.name} item.is_create_recipe {item.is_create_recipe} item.is_ready {item.is_ready} check_recipe.custom_is_recipe {check_recipe.custom_is_recipe}"
                print(log_message)
              
                find_default_bom=frappe.get_doc("BOM",{"item":item.item,"is_default":1})
                if bool(find_default_bom):
                    frappe.enqueue(run_bom_process,queue="long",bom_id=find_default_bom.name,qty=item.qty,order_id=self.name)
    def update_order_placed_time(self):
        if self.status == 'Work in progress':
            order_items=self.item_list
            for item in order_items:
                if not item.order_placed_time:
                    item.order_placed_time=self.modified
        if self.status == 'Preparing':
            order_items=self.item_list
            for item in order_items:
                if not item.order_accepted_time:
                    item.order_accepted_time=self.modified
        
        if self.status == 'Ready to Serve':
            order_items=self.item_list
            for item in order_items:
                if not item.order_ready_time:
                    item.order_ready_time=self.modified
        if self.status == 'Completed':
            order_items=self.item_list
            for item in order_items:
                if not item.order_confirm_time:
                    item.order_confirm_time=self.modified