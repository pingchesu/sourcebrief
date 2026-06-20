import type { Metadata } from 'next';
import type { ReactNode } from 'react';
import './globals.css';
import { AppShell } from '../components/AppShell';
import { PlatformProvider } from '../lib/platform-context';

export const metadata: Metadata = {
  title: 'SourceBrief',
  description: 'Enterprise knowledge-agent platform console',
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <PlatformProvider>
          <AppShell>{children}</AppShell>
        </PlatformProvider>
      </body>
    </html>
  );
}
