import Foundation
import Combine

class NetworkManager: ObservableObject {
    private var webSocket: URLSessionWebSocketTask?
    @Published var messages: [String] = []
    
    func connect(sessionID: String) {
        let url = URL(string: "ws://localhost:8000/ws/voice?session_id=\(sessionID)")!
        webSocket = URLSession.shared.webSocketTask(with: url)
        webSocket?.resume()
        receiveMessage()
    }
    
    func send(text: String, intent: String? = nil, slots: [String: String]? = nil) {
        let payload: [String: Any] = [
            "text": text,
            "intent": intent as Any,
            "slots": slots as Any
        ].compactMapValues { $0 }
        
        if let data = try? JSONSerialization.data(withJSONObject: payload),
           let jsonString = String(data: data, encoding: .utf8) {
            webSocket?.send(.string(jsonString)) { error in
                if let error = error {
                    print("WebSocket send error: \(error)")
                }
            }
        }
    }
    
    private func receiveMessage() {
        webSocket?.receive { [weak self] result in
            switch result {
            case .success(let message):
                switch message {
                case .string(let text):
                    DispatchQueue.main.async {
                        self?.messages.append(text)
                    }
                default: break
                }
                self?.receiveMessage()
            case .failure(let error):
                print("WebSocket receive error: \(error)")
            }
        }
    }
}
