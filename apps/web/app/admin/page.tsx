'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { Card, PageHeader } from '../../components/ui';

export default function AdminRedirectPage() {
  const router = useRouter();
  useEffect(() => { router.replace('/users'); }, [router]);
  return <main className="page"><PageHeader eyebrow="Administration" title="Admin moved to Team Access" description="User and role administration now lives in the Team Access page." /><Card><p className="muted">Redirecting to Team Access…</p></Card></main>;
}
