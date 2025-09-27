import streamlit as st
import pandas as pd
import numpy as np
import vitaldb
import os
import plotly.graph_objects as go

# --- Basic Settings and Paths ---
PROCESSED_LABEL_DIR = "./LabelFile/Annotation_Files_250907"
METADATA_FILE = "./LabelFile/metadata.csv"
PLOT_DURATION = 12  # in seconds


# --- Data Loading Functions (with Caching) ---
@st.cache_data
def load_metadata():
    if not os.path.exists(METADATA_FILE): return None
    return pd.read_csv(METADATA_FILE)

@st.cache_data
def load_annotation_data(case_id):
    file_path = os.path.join(PROCESSED_LABEL_DIR, f"Annotation_file_{case_id}.csv")
    if not os.path.exists(file_path): return None
    return pd.read_csv(file_path)

@st.cache_data
def load_waveform_data(case_id):
    """Downloads and caches waveform data via the VitalDB API."""
    try:
        vf = vitaldb.VitalFile(int(case_id))
        ecg_data = vf.to_numpy(['ECG_II'], 1/100)[:, 0]
        return ecg_data
    except Exception as e:
        st.error(f"An error occurred while fetching waveform data: {e}")
        return None

# --- Plotting Function using Plotly (Unchanged) ---
def plot_segment_plotly(case_id, ecg_data, df, start_time, end_time, sample_rate=100):
    fs = sample_rate
    start_idx, end_idx = int(start_time * fs), int(end_time * fs)
    if start_idx < 0 or end_idx > len(ecg_data): return None

    ecg_segment = ecg_data[start_idx:end_idx]
    time_axis = np.arange(start_idx, end_idx) / fs
    if len(ecg_segment) == 0: return None

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=time_axis, y=ecg_segment, mode='lines', name='ECG', line=dict(color='green')))

    if df is not None:
        segment_df = df[(df['time_second'] >= start_time) & (df['time_second'] <= end_time)]
        beat_markers = {'N': 'circle', 'S': 'triangle-up', 'V': 'square', 'U': 'star'}
        for beat_type, marker_symbol in beat_markers.items():
            beats = segment_df[segment_df['beat_type'] == beat_type]
            if not beats.empty:
                beat_times = beats['time_second'].values
                beat_indices = (beat_times * fs - start_idx).astype(int)
                valid_indices = (beat_indices >= 0) & (beat_indices < len(ecg_segment))
                fig.add_trace(go.Scatter(
                    x=beat_times[valid_indices], y=ecg_segment[beat_indices[valid_indices]],
                    mode='markers', name=f'Beat: {beat_type}',
                    marker=dict(symbol=marker_symbol, color='black', size=8)
                ))
        if 'bad_signal_quality' in segment_df.columns and segment_df['bad_signal_quality'].any():
            bad_times = segment_df[segment_df['bad_signal_quality'] == True]['time_second'].sort_values()
            if not bad_times.empty:
                fig.add_vrect(x0=bad_times.min(), x1=bad_times.max(), fillcolor="lightgrey", opacity=0.5,
                              layer="below", line_width=0, name='Bad Signal')
    fig.update_layout(
        title=f"Case ID: {case_id} | Time: {start_time:.1f}s - {end_time:.1f}s",
        xaxis_title="Time (seconds)", yaxis_title="Amplitude (mV)", showlegend=True
    )
    return fig

# --- Streamlit Web Application UI ---
def main():
    st.set_page_config(layout="wide")
    st.title("🩺 VitalDB Arrhythmia Explorer")

    metadata_df = load_metadata()
    if metadata_df is None:
        st.error(f"Could not find '{METADATA_FILE}'. Please check the path and filename.")
        st.stop()

    st.sidebar.header("Navigation")
    all_rhythms = sorted(metadata_df['rhythm_classes'].str.split(', ').explode().unique())
    selected_rhythm = st.sidebar.selectbox("1. Select a Rhythm Label:", all_rhythms)

    if selected_rhythm:
        cases_with_rhythm = metadata_df[metadata_df['rhythm_classes'].str.contains(selected_rhythm, na=False)]
        case_ids = sorted(cases_with_rhythm['case_id'].unique())
        selected_case_id = st.sidebar.selectbox("2. Select a Case ID:", case_ids)

        if selected_case_id:
            annotation_df = load_annotation_data(selected_case_id)
            if annotation_df is None:
                st.error(f"Annotation file for Case ID {selected_case_id} not found.")
                st.stop()

            ecg_data = load_waveform_data(selected_case_id)
            if ecg_data is None:
                st.error("Failed to load waveform data.")
                st.stop()

            if 'current_case' not in st.session_state or \
               st.session_state.current_case != selected_case_id or \
               st.session_state.current_rhythm != selected_rhythm:
                st.session_state.current_case = selected_case_id
                st.session_state.current_rhythm = selected_rhythm
                st.session_state.segment_index = 0

            rhythm_segments = annotation_df[annotation_df['rhythm_label'] == selected_rhythm]
            rhythm_starts = rhythm_segments.loc[rhythm_segments['time_second'].diff().fillna(999) > 1, 'time_second'].tolist()
            
            if not rhythm_starts:
                st.warning(f"Could not find a clear starting segment for the label '{selected_rhythm}'.")
                st.stop()

            # Arrange navigation buttons on either side of the plot
            left_col, center_col, right_col = st.columns([1, 12, 1])

            with left_col:
                st.write("") # Spacer for vertical alignment
                st.write("")
                if st.button("⬅️", use_container_width=True):
                    st.session_state.segment_index = max(0, st.session_state.segment_index - 1)
            
            with right_col:
                st.write("") # Spacer for vertical alignment
                st.write("")
                if st.button("➡️", use_container_width=True):
                    st.session_state.segment_index = min(len(rhythm_starts) - 1, st.session_state.segment_index + 1)
            
            # Display the plot in the central column
            with center_col:
                st.info(f"Showing segment **{st.session_state.segment_index + 1}** of **{len(rhythm_starts)}** for rhythm: **'{selected_rhythm}'**")

                start_time = rhythm_starts[st.session_state.segment_index]
                end_time = start_time + PLOT_DURATION
                
                fig = plot_segment_plotly(selected_case_id, ecg_data, annotation_df, start_time, end_time)
                
                if fig:
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.error("Could not generate the plot. Please check the data range.")

if __name__ == "__main__":
    main()