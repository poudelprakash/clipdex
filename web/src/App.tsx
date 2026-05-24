import { Route, Routes } from "react-router-dom";
import { GuestPage } from "./pages/GuestPage";
import { Home } from "./pages/Home";
import { Search } from "./pages/Search";

export function App() {
  return (
    <Routes>
      <Route path="/" element={<Home />} />
      <Route path="/guests/:guestId" element={<GuestPage />} />
      <Route path="/search" element={<Search />} />
    </Routes>
  );
}
