import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";
import "./globals.css";

export const metadata: Metadata = {
  title: "ARO 3D AI Studio",
  description: "Turn an image into a game-ready 3D model.",
};
export const viewport: Viewport = { themeColor: "#0f1115", colorScheme: "dark light" };

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
