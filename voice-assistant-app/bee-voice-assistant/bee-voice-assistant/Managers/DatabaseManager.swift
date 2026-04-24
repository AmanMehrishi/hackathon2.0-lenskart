import Foundation

class DatabaseManager {
    static let shared = DatabaseManager()
    
    private let storeDetails = [
        "NY01": ["name": "Lenskart NYC", "inventory": "High", "address": "123 Broadway, New York"],
        "CA05": ["name": "Lenskart SF", "inventory": "Medium", "address": "456 Market St, San Francisco"],
        "TX12": ["name": "Lenskart Austin", "inventory": "Low", "address": "789 Tech Blvd, Austin"]
    ]
    
    private let orders = [
        "12345": ["status": "Shipped", "item": "Vincent Chase Aviators", "eta": "2 Days"],
        "67890": ["status": "Processing", "item": "John Jacobs Wayfarers", "eta": "5 Days"],
        "54321": ["status": "Delivered", "item": "Lenskart Blu Glasses", "eta": "N/A"]
    ]
    
    func getOrderDetail(orderId: String) -> String {
        guard let order = orders[orderId] else {
            return "Order not found in local database."
        }
        return "Order \(orderId) status is \(order["status"]!). The item is \(order["item"]!) and ETA is \(order["eta"]!)."
    }
    
    func getStoreInfo(storeId: String) -> String {
        guard let store = storeDetails[storeId.uppercased()] else {
            return "Store ID not recognized."
        }
        return "\(store["name"]!) is located at \(store["address"]!). Current inventory level is \(store["inventory"]!)."
    }
}
