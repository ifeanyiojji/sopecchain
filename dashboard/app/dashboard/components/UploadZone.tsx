'use client';
import { useState, useCallback } from "react";

export const UploadZone = ({ onFilesUploaded }: { onFilesUploaded: (files: File[]) => void }) => {
  const [dragOver, setDragOver] = useState(false);

  const handleInputChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const files = event.target.files;
    if (files && files.length > 0) {
      onFilesUploaded(Array.from(files));
    }
  };

  const handleDrop = useCallback((event: React.DragEvent) => {
    event.preventDefault();
    setDragOver(false);
    const files = Array.from(event.dataTransfer.files).filter(
      (f) => f.name.endsWith(".csv") || f.name.endsWith(".pdf")
    );
    if (files.length > 0) {
      onFilesUploaded(files);
    }
  }, [onFilesUploaded]);

  const handleDragOver = (event: React.DragEvent) => {
    event.preventDefault();
    setDragOver(true);
  };

  const handleDragLeave = () => {
    setDragOver(false);
  };

  return (
    <label
      htmlFor="fileUpload"
      className="cursor-pointer block"
      onDrop={handleDrop}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
    >
      <input
        type="file"
        multiple
        accept=".csv,.pdf"
        className="hidden"
        id="fileUpload"
        onChange={handleInputChange}
      />
      <div
        className={`text-center p-10 border-2 border-dashed rounded-xl transition-colors ${
          dragOver
            ? "border-emerald-600 bg-emerald-100"
            : "border-emerald-400 bg-emerald-50"
        }`}
      >
        <div className="text-emerald-600 text-5xl mb-2">+</div>
        <p className="text-xl font-semibold text-emerald-600">
          Drop CSV or PDF files here, or click to browse
        </p>
        <p className="text-sm text-emerald-500 mt-1">
          Supports operational data, field tickets, and invoices
        </p>
      </div>
    </label>
  );
};
