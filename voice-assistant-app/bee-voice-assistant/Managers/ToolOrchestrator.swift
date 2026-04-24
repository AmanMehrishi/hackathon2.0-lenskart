import Foundation

class ToolOrchestrator {
    private let llmManager: LLMManager
    private let networkManager: NetworkManager
    
    init(llmManager: LLMManager, networkManager: NetworkManager) {
        self.llmManager = llmManager
        self.networkManager = networkManager
    }
    
    func processTurn(text: String, intent: String, slots: [String: String], history: [[String: String]]) async -> String {
        let systemPrompt = """
        You are a Lenskart voice assistant running on-device. Help the user with their request.
        Intent: \(intent)
        Slots: \(slots)
        
        If you need to call a tool, output JSON: {"tool": "tool_name", "args": {...}}
        Tools: get_order_detail, search_catalog, get_orders, get_store_info, ESCALATE
        """
        
        let response = await llmManager.generateResponse(userText: text, history: history, systemPrompt: systemPrompt)
        
        // Check if response is a tool call
        if response.contains("\"tool\":") {
            // Forward tool call to backend for execution (since DB is there)
            networkManager.send(text: text, intent: intent, slots: slots)
            return "Executing request..."
        }
        
        return response
    }
}
