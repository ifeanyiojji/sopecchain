import "./globals.css";

export const metadata = {
  title: "ScopeChain",
  description: "Scope 3 Dashboard",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
