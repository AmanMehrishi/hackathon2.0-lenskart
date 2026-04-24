import Foundation
import Combine

class ChatViewModel: ObservableObject {
    @Published var transcription = ""
    @Published var messages: [String] = []
    @Published var isRecording = false
    
    private let speechManager = SpeechManager()
    private let networkManager = NetworkManager()
    private var classifier: NGramClassifier?
    private var llmManager: LLMManager?
    private var toolOrchestrator: ToolOrchestrator?
    private var history: [[String: String]] = []
    private var cancellables = Set<AnyCancellable>()
    
    init() {
        setupEdgeIntelligence()
        
        speechManager.$transcribedText
            .assign(to: \.transcription, on: self)
            .store(in: &cancellables)
            
        speechManager.$isRecording
            .assign(to: \.isRecording, on: self)
            .store(in: &cancellables)
            
        networkManager.$messages
            .sink { [weak self] msgs in
                if let last = msgs.last {
                    self?.messages.append(last)
                    self?.speechManager.speak(last)
                }
            }
            .store(in: &cancellables)
            
        networkManager.connect(sessionID: "swift_session_\(Int.random(in: 1000...9999))")
    }
    
    private func setupEdgeIntelligence() {
        // 1. Classifier
        if let path = Bundle.main.path(forResource: "intents", ofType: "json"),
           let data = try? Data(contentsOf: URL(fileURLWithPath: path)),
           let config = try? JSONDecoder().decode(IntentConfig.self, from: data) {
            self.classifier = NGramClassifier(config: config)
        }
        
        // 2. LLM Manager (Edge)
        // Check App Bundle first (Portable for iPhone)
        var modelPath = Bundle.main.path(forResource: "Llama-3.2-3B-Instruct", ofType: nil)
        
        // Fallback to local Mac path for development/simulators
        if modelPath == nil {
            modelPath = "/Users/amanmehrishi/Documents/Hackathon2.0/Llama-3.2-3B-Instruct"
        }
        
        if let actualPath = modelPath {
            let runner = MLXLLMRunner(modelPath: actualPath)
            self.llmManager = LLMManager(runner: runner)
        }
        
        // 3. Orchestrator
        if let llm = llmManager {
            self.toolOrchestrator = ToolOrchestrator(llmManager: llm, networkManager: networkManager)
        }
    }
    
    func toggleRecording() {
        if isRecording {
            speechManager.stopRecording()
            Task {
                await processText(transcription)
            }
        } else {
            transcription = ""
            speechManager.startRecording()
        }
    }
    
    private func processText(_ text: String) async {
        guard !text.isEmpty else { return }
        
        await MainActor.run {
            messages.append("User: \(text)")
            history.append(["role": "user", "content": text])
        }
        
        if let classifier = classifier, let orchestrator = toolOrchestrator {
            let match = classifier.classify(text)
            print("Edge Intent: \(match.intent)")
            
            let response = await orchestrator.processTurn(text: text, intent: match.intent, slots: match.slots, history: history)
            
            await MainActor.run {
                if !response.isEmpty && response != "Executing request..." {
                    messages.append("Assistant (Local): \(response)")
                    history.append(["role": "assistant", "content": response])
                    speechManager.speak(response)
                }
            }
        } else {
            networkManager.send(text: text)
        }
    }
}
