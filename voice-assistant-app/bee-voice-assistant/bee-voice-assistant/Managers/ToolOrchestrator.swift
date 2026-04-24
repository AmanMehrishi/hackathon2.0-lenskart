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
        You are a smart voice assistant running on-device for Lenskart. Answer the user nicely.
        If you need specific data (like an order status or store details), output ONLY a JSON object to call a tool, like this:
        {"tool": "get_order_detail", "args": {"order_id": "12345"}}
        {"tool": "get_store_info", "args": {"store_id": "NY01"}}
        
        If you want to escalate to a human or cloud backend because the request is very complex, output exactly: ESCALATE
        """
        
        print("Tier 2: Processing user request locally...")
        let response = await llmManager.generateResponse(userText: text, history: history, systemPrompt: systemPrompt)
        
        let trimmedResponse = response.trimmingCharacters(in: .whitespacesAndNewlines)
        
        // Check for Cloud Escalation
        if trimmedResponse.contains("ESCALATE") {
            print("Tier 2: Escalating to Tier 3 (Cloud)...")
            networkManager.send(text: text, intent: intent, slots: slots)
            return "This seems complex! Let me grab that from the cloud..."
        }
        
        // Tier 2 Logic: Check for Tool Call JSON pattern
        if trimmedResponse.contains("{") && trimmedResponse.contains("tool") {
            print("Tier 2: Detected potential Tool Call => \(trimmedResponse)")
            if let jsonMetadata = parseToolCall(from: trimmedResponse) {
                let toolName = jsonMetadata.tool
                let args = jsonMetadata.args
                
                print("Tier 2: Executing tool `\(toolName)` locally...")
                var toolResult = "Tool did not execute properly."
                
                if toolName == "get_order_detail", let orderId = args["order_id"] {
                    toolResult = DatabaseManager.shared.getOrderDetail(orderId: orderId)
                } else if toolName == "get_store_info", let storeId = args["store_id"] {
                    toolResult = DatabaseManager.shared.getStoreInfo(storeId: storeId)
                } else {
                    // Forward unknown tool call to backend
                    print("Tier 2: Tool `\(toolName)` not registered locally. Sending to backend.")
                    networkManager.send(text: text, intent: intent, slots: slots)
                    return "Checking with the cloud server..."
                }
                
                // Feedback loop: Give the tool output back to the LLM to form a conversational answer
                let followUpPrompt = "The tool returned this data: \(toolResult)\nAnswer the user based ONLY on this data."
                print("Tier 2: Feeding tool result back to LLM...")
                return await llmManager.generateResponse(userText: followUpPrompt, history: history, systemPrompt: systemPrompt)
            }
        }
        
        // Normal conversational response from Llama
        return trimmedResponse
    }
    
    // Helper to extract JSON from LLM output (since it might output conversational prefix/suffix)
    private func parseToolCall(from text: String) -> (tool: String, args: [String: String])? {
        guard let start = text.firstIndex(of: "{"), let end = text.lastIndex(of: "}") else { return nil }
        let jsonString = String(text[start...end])
        
        guard let data = jsonString.data(using: .utf8),
              let dict = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let toolStr = dict["tool"] as? String else {
            return nil
        }
        
        let argsDict = dict["args"] as? [String: String] ?? [:]
        return (tool: toolStr, args: argsDict)
    }
}
