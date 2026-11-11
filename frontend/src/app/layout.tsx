import type { Metadata, Viewport } from "next";
import { AuthProvider, ToastProvider } from "@/components/providers";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "TEC THA Follow-Up Engine", template: "%s · TEC THA" },
  description: "Appointment booking and WhatsApp follow-up reminders for hospitals and clinics.",
  robots: { index: false, follow: false },
};

export const viewport: Viewport = { themeColor: "#121214", width: "device-width", initialScale: 1 };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-dvh antialiased">
        <ToastProvider>
          <AuthProvider>{children}</AuthProvider>
        </ToastProvider>
      </body>
    </html>
  );
}
