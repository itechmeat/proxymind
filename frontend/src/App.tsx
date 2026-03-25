import { BrowserRouter, Route, Routes } from "react-router";

import { ChatPage } from "@/pages/ChatPage";

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<ChatPage />} path="/" />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
