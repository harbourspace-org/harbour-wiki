import { NextRequest, NextResponse } from "next/server";

import { createAnnotation, listAnnotations } from "@/lib/annotations";

export async function GET(req: NextRequest) {
  const course = req.nextUrl.searchParams.get("course");
  const concept = req.nextUrl.searchParams.get("concept");
  if (!course || !concept) {
    return NextResponse.json({ error: "course and concept are required" }, { status: 400 });
  }
  return NextResponse.json({ annotations: await listAnnotations(course, concept) });
}

export async function POST(req: NextRequest) {
  const { course, concept, body, author } = await req.json().catch(() => ({}));
  if (!course || !concept || !body?.trim()) {
    return NextResponse.json({ error: "course, concept, body required" }, { status: 400 });
  }
  const annotation = await createAnnotation(course, concept, body.trim(), author);
  return NextResponse.json({ annotation }, { status: 201 });
}
