import Foundation

protocol LLMRunner {
    func generate(prompt: String) async -> String
}

class LLMManager: ObservableObject {
    private let runner: LLMRunner
    
    init(runner: LLMRunner) {
        self.runner = runner
    }
    
    func generateResponse(userText: String, history: [[String: String]], systemPrompt: String) async -> String {
        // Construct chat template
        var prompt = "<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n\n\(systemPrompt)<|eot_id|>"
        
        for turn in history {
            let role = turn["role"] ?? "user"
            let content = turn["content"] ?? ""
            prompt += "<|start_header_id|>\(role)<|end_header_id|>\n\n\(content)<|eot_id|>"
        }
        
        prompt += "<|start_header_id|>user<|end_header_id|>\n\n\(userText)<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n"
        
        return await runner.generate(prompt: prompt)
    }
}

// Concrete implementation using MLX-Swift style (Mockable for now)
class MLXLLMRunner: LLMRunner {
    private let modelPath: String
    
    init(modelPath: String) {
        self.modelPath = modelPath
    }
    
    func generate(prompt: String) async -> String {
        // In a real app, you would use MLXLLM.shared.generate(...)
        // For the purpose of this hackathon demo, we provide the hook.
        print("Edge LLM (MLX) generating for prompt: \(prompt.suffix(100))...")
        
        // Simulating network/computation delay
        try? await Task.sleep(nanoseconds: 1_000_000_000)
        
        // This is where the actual local Llama 3.2 would process.
        // We'll return a marker to show it's running locally.
        return "[Local LLM] I understand your request. Let me check that for you."
    }
}
