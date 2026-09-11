import React from "react";
import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import axios from "axios";

import Coach from "@/pages/Coach";
import { LanguageProvider } from "@/context/LanguageContext";
import { useAuth } from "@/context/AuthContext";

jest.mock("axios");
jest.mock("sonner", () => ({
  toast: { success: jest.fn(), error: jest.fn() },
}));
jest.mock("@/context/AuthContext", () => ({
  useAuth: jest.fn(),
}));

describe("Coach page", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    useAuth.mockReturnValue({ user: { id: "u1" } });
    axios.get.mockResolvedValue({ data: [] });
  });

  test("empty state stays advisory and does not fabricate a prescription", async () => {
    render(
      <LanguageProvider>
        <MemoryRouter>
          <Coach />
        </MemoryRouter>
      </LanguageProvider>
    );

    expect(await screen.findByText(/only prescription authority/i)).toBeInTheDocument();
    expect(screen.getByText(/Open today and training/i)).toBeInTheDocument();
    expect(screen.queryByText(/Tempo|Intervals|Long run/i)).not.toBeInTheDocument();
  });
});
